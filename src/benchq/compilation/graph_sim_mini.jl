################################################################################
# © Copyright 2022-2023 Zapata Computing Inc.
################################################################################
#=
This module contains functions for getting the graph state corresponding to a
state generated by a circuit using a graph state simulator (graph_sim) from the paper
"Fast simulation of stabilizer circuits using a graph state representation" by Simon
Anders, Hans J. Briegel. https://arxiv.org/abs/quant-ph/0504117". We have modified
the algorithm to ignore paulis.
=#

using PythonCall

include("graph_sim_data.jl")

const AdjList = Set{Int32}

const Qubit = UInt32

struct ICMOp
    code::LCO
    qubit1::Qubit
    qubit2::Qubit

ICMOp(name, qubit) = new(name, qubit+1, 0)
ICMOp(name, qubit1, qubit2) = new(name, qubit1+1, qubit2+1)
end

"""
Get the vertices of a graph state corresponding to enacting the given circuit
on the |0> state. Also gives the local clifford operation on each node.

Args:
    circuit (Circuit): circuit to get the graph state for

Raises:
    ValueError: if an unsupported gate is encountered

Returns:
    Vector{LCO}: the list of local clifford operations on each node
    Vector{AdjList}:   the adjacency list describing the graph corresponding to the graph state
"""
function get_graph_state_data(icm_circuit::Vector{ICMOp}, n_qubits, display=false)
    lco = fill(H_code, n_qubits)   # local clifford operation on each node
    adj = [AdjList() for _ in 1:n_qubits]  # adjacency list

    if display
        total_length = length(icm_circuit)
        counter = dispcnt = 0
        start_time = time()
        erase = "        \b\b\b\b\b\b\b\b"
    end


    for icm_op in icm_circuit
        if display
            counter += 1
            if (dispcnt += 1) >= 1000
                percent = round(Int, 100 * counter / total_length)
                elapsed = round(time() - start_time, digits=2)
                print("\r$(percent)% ($counter) completed in $erase$(elapsed)s")
                dispcnt = 0
            end
        end

        op_code = icm_op.code
        qubit_1 = icm_op.qubit1
        if op_code == H_code
            lco[qubit_1] = multiply_h(lco[qubit_1])
        elseif op_code == S_code
            lco[qubit_1] = multiply_s(lco[qubit_1])
        elseif op_code == CNOT_code
            # CNOT = (I ⊗ H) CZ (I ⊗ H)
            qubit_2 = icm_op.qubit2
            lco[qubit_2] = multiply_h(lco[qubit_2])
            cz(lco, adj, qubit_1, qubit_2)
            lco[qubit_2] = multiply_h(lco[qubit_2])
        elseif op_code == CZ_code
            cz(lco, adj, qubit_1, icm_op.qubit2)
        elseif op_code != Pauli_code
            error("Unrecognized gate code $op_code encountered")
        end
    end

    if display
        elapsed = round(time() - start_time, digits=2)
        println("\r100% ($counter) completed in $erase$(elapsed)s")
    end

    return lco, adj
end

"""Unpacks the values in the cz table and updates the lco values)"""
@inline function update_lco(table, lco, vertex_1, vertex_2)
    # Get the packed value from the table
    val = table[lco[vertex_1], lco[vertex_2]]
    # The code for the first vertex is stored in the top nibble
    # and the second in the bottom nibble
    lco[vertex_1] = (val >> 4) & 0x7
    lco[vertex_2] = val & 0x7
    # return if the top bit is set, which indicates if it is isolated or connected
    (val & 0x80) != 0x00
end

"""
Check if a vertex is almost isolated. A vertex is almost isolated if it has no
neighbors or if it has one neighbor and that neighbor is the given vertex.

Args:
    set::AdjList set of neighbors of a vertex
    vertex::Int  vertex to check if it is almost isolated

Returns:
    Bool: whether the vertex is almost isolated
"""
function check_almost_isolated(set, vertex)
    len = length(set)
    return (len == 0) || (len == 1 && vertex in set)
end

"""
Apply a CZ gate to the graph on the given vertices.

Args:
    lco::Vector{LCO}      local clifford operation on each node
    adj::Vector{AdjList}  adjacency list describing the graph state
    vertex_1::Int         vertex to enact the CZ gate on
    vertex_2::Int         vertex to enact the CZ gate on
"""
function cz(lco, adj, vertex_1, vertex_2)
    lst1, lst2 = adj[vertex_1], adj[vertex_2]

    if check_almost_isolated(lst1, vertex_2)
        check_almost_isolated(lst2, vertex_1) || remove_lco!(lco, adj, vertex_2, vertex_1)
        # if you don't remove vertex_2 from lst1, then you don't need to check again
    else
        remove_lco!(lco, adj, vertex_1, vertex_2)
        if !check_almost_isolated(lst2, vertex_1)
            remove_lco!(lco, adj, vertex_2, vertex_1)
            # recheck the adjacency list of vertex_1, because it might have been removed
            check_almost_isolated(lst1, vertex_2) || remove_lco!(lco, adj, vertex_1, vertex_2)
        end
    end
    if vertex_2 in lst1
        update_lco(cz_connected, lco, vertex_1, vertex_2) || remove_edge!(adj, vertex_1, vertex_2)
    else
        update_lco(cz_isolated, lco, vertex_1, vertex_2) && add_edge!(adj, vertex_1, vertex_2)
    end
end

"""
Select a neighbor to use when removing an LCO

The return value be set to avoid if there are no neighbors or avoid is the only neighbor,
otherwise it returns the neighbor with the fewest neighbors (or the first one that
it finds with less than min_neighbors)
"""
function get_neighbor(adj, v, avoid, min_neighbors = 6)
    neighbors_of_v = adj[v]

    # Avoid copying and modifying adjacency vector
    check_almost_isolated(neighbors_of_v, avoid) && return avoid

    smallest_neighborhood_size = typemax(eltype(neighbors_of_v)) # initialize to max possible value
    neighbor_with_smallest_neighborhood = 0
    for neighbor in neighbors_of_v
        if neighbor != avoid
            # stop search if  super small neighborhood is found
            num_neighbors = length(adj[neighbor])
            num_neighbors < min_neighbors && return neighbor
            # search for smallest neighborhood
            if num_neighbors < smallest_neighborhood_size
                smallest_neighborhood_size = num_neighbors
                neighbor_with_smallest_neighborhood = neighbor
            end
        end
    end
    return neighbor_with_smallest_neighborhood
end

"""
Remove all local clifford operations on a vertex v that do not commute
with CZ. Needs use of a neighbor of v, but if we wish to avoid using
a particular neighbor, we can specify it.

Args:
    lco::Vector{LCO}      local clifford operations on each node
    adj::Vector{AdjList}  adjacency list describing the graph state
    v::Int                index of the vertex to remove local clifford operations from
    avoid::Int            index of a neighbor of v to avoid using
"""
function remove_lco!(lco, adj, v, avoid)
    code = lco[v]
    if code == Pauli_code || code == S_code
    elseif code == SQRT_X_code
        local_complement!(lco, adj, v)
    else
        if code == SH_code
            local_complement!(lco, adj, v)
            vb = get_neighbor(adj, v, avoid)
            local_complement!(lco, adj, vb)
        else # code == H_code || code == HS_code
            vb = get_neighbor(adj, v, avoid)
            local_complement!(lco, adj, vb)
            local_complement!(lco, adj, v)
        end
    end
end

"""
Take the local complement of a vertex v.

Args:
    lco::Vector{LCO}      local clifford operations on each node
    adj::Vector{AdjList}  adjacency list describing the graph state
    v::Int                index node to take the local complement of
"""
function local_complement!(lco, adj, v)
    neighbors = collect(adj[v])
    len = length(neighbors)
    for i in 1:len
        neighbor = neighbors[i]
        for j in i+1:len
            toggle_edge!(adj, neighbor, neighbors[j])
        end
    end
    lco[v] = multiply_by_sqrt_x(lco[v])
    for i in adj[v]
        lco[i] = multiply_by_s(lco[i])
    end
end

"""Add an edge between the two vertices given"""
@inline function add_edge!(adj, vertex_1, vertex_2)
    push!(adj[vertex_1], vertex_2)
    push!(adj[vertex_2], vertex_1)
end

"""Remove an edge between the two vertices given"""
@inline function remove_edge!(adj, vertex_1, vertex_2)
    delete!(adj[vertex_1], vertex_2)
    delete!(adj[vertex_2], vertex_1)
end

"""
If vertices vertex_1 and vertex_2 are connected, we remove the edge.
Otherwise, add it.

Args:
    adj::Vector{AdjList}  adjacency list describing the graph state
    vertex_1::Int         index of vertex to be connected or disconnected
    vertex_2::Int         index of vertex to be connected or disconnected
"""
function toggle_edge!(adj, vertex_1, vertex_2)
    # if insorted(vertex_2, adj[vertex_1])
    if vertex_2 in adj[vertex_1]
        remove_edge!(adj, vertex_1, vertex_2)
    else
        add_edge!(adj, vertex_1, vertex_2)
    end
end

get_qubit_1(op) = pyconvert(Int, op.qubit_indices[0])
get_qubit_2(op) = pyconvert(Int, op.qubit_indices[1])

const op_list = ["I", "X", "Y", "Z", "H", "S", "S_Dagger", "CZ", "CNOT",
                 "T", "T_Dagger", "RX", "RY", "RZ", "SX", "SX_Dagger", "RESET"]
const code_list = LCO[0, 0, 0, 0, H_code, S_code, S_Dagger_code, CZ_code, CNOT_code,
                      T_code, T_Dagger_code, RX_code, RY_code, RZ_code, SQRT_X_code, SQRT_X_code, 0]

"""Get Python version of op_list of to speed up getting index"""
get_op_list() = pylist(op_list)

"""Get index of operation name"""
get_op_index(op_list, op) = pyconvert(Int, op_list.index(op.gate.name)) + 1

pauli_op(index) = index < 5 # i.e. I, X, Y, Z
single_qubit_op(index) = 4 < index < 8   # H, S, S_Dagger
double_qubit_op(index) = 7 < index < 10  # CZ, CNOT
decompose_op(index) = index > 9 # T, T_Dagger, RX, RY, RZ

"""
Performs gates decomposition to provide a circuit in the icm format.
Reference: https://arxiv.org/abs/1509.02004
"""
function get_icm(circuit, n_qubits::Int, with_measurements::Bool=false)
    # mapping from qubit to its compiled version
    qubit_map = [Qubit(i) for i = 0:n_qubits-1]
    compiled_circuit = ICMOp[]
    ops = get_op_list()
    curr_qubits = n_qubits
    for op in circuit
        if occursin("ResetOperation", pyconvert(String, op.__str__()))
            original_qubit = get_qubit_1(op)
            compiled_qubit = qubit_map[original_qubit+1]
            qubit_map[original_qubit+1] = new_qubit = curr_qubits
            curr_qubits += 1
        else
            op_index = get_op_index(ops, op)
            if single_qubit_op(op_index)
                push!(compiled_circuit, ICMOp(code_list[op_index], qubit_map[get_qubit_1(op)+1]))
            elseif double_qubit_op(op_index)
                push!(compiled_circuit,
                    ICMOp(code_list[op_index],
                            qubit_map[get_qubit_1(op)+1], qubit_map[get_qubit_2(op)+1]))
            elseif decompose_op(op_index)
                # Note: these are currently all single qubit gates
                original_qubit = get_qubit_1(op)
                compiled_qubit = qubit_map[original_qubit+1]
                qubit_map[original_qubit+1] = new_qubit = curr_qubits
                curr_qubits += 1

                push!(compiled_circuit, ICMOp(CNOT_code, compiled_qubit, new_qubit))
                with_measurements &&
                    push!(compiled_circuit,
                        ICMOp(code_list[op_index]+MEASURE_OFFSET, compiled_qubit, new_qubit))
            end
        end
    end

    return compiled_circuit, curr_qubits
end

"""
Destructively convert this to a Python adjacency list
"""
function python_adjlist!(adj)
    pylist([pylist(adj[i] .- 1) for i in 1:length(adj)])
end

"""
Converts a given circuit in Clifford + T form to icm form and simulates the icm
circuit using the graph sim mini simulator. Returns the adjacency list of the graph
state created by the icm circuit along with the single qubit operations on each vertex.

Args:
    circuit::Circuit  circuit to be simulated

Returns:
    adj::Vector{AdjList}  adjacency list describing the graph state
    lco::Vector{LCO}      local clifford operations on each node
"""
function run_graph_sim_mini(circuit, display=false)
    n_qubits = pyconvert(Int, circuit.n_qubits)
    ops = circuit.operations
    if display
        @time begin
            print("\nGraph Sim Mini: qubits=$n_qubits, gates=$(length(ops))")
            (icm_circuit, icm_n_qubits) = get_icm(ops, n_qubits)
            print(" => $icm_n_qubits, $(length(icm_circuit))\n\t")
        end
        print("get_graph_state_data:\t")
        (lco, adj) = @time get_graph_state_data(icm_circuit, icm_n_qubits, true)
    else
        (icm_circuit, icm_n_qubits) = get_icm(ops, n_qubits)
        (lco, adj) = get_graph_state_data(icm_circuit, icm_n_qubits, false)
    end
    return pylist(lco), python_adjlist!(adj)
end
