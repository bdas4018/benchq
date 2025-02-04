################################################################################
# © Copyright 2022-2023 Zapata Computing Inc.
################################################################################
import os

import numpy as np
import pytest
import stim
from numba import njit
from orquestra.integrations.qiskit.conversions import import_from_qiskit
from orquestra.quantum.circuits import CNOT, CZ, Circuit, H, S, X
from qiskit import QuantumCircuit

from benchq.compilation import (
    jl,
    pyliqtr_transpile_to_clifford_t,
    transpile_to_native_gates,
)


@pytest.mark.parametrize(
    "circuit",
    [
        Circuit([X(0)]),
        Circuit([H(0)]),
        Circuit([S(0)]),
        Circuit([H(0), S(0), H(0)]),
        Circuit([H(0), S(0)]),
        Circuit([S(0), H(0)]),
        Circuit([S.dagger(0)]),
        Circuit([H(2)]),
        Circuit([H(0), CNOT(0, 1)]),
        Circuit([CZ(0, 1), H(2)]),
        Circuit([H(0), S(0), CNOT(0, 1), H(2)]),
        Circuit([CNOT(0, 1), CNOT(1, 2)]),
        Circuit(
            [
                H(0),
                S(0),
                H(1),
                CZ(0, 1),
                H(2),
                CZ(1, 2),
            ]
        ),
        Circuit(
            [
                H(0),
                H(1),
                H(3),
                CZ(0, 3),
                CZ(1, 4),
                H(3),
                H(4),
                CZ(3, 4),
            ]
        ),
    ],
)
def test_stabilizer_states_are_the_same_for_simple_circuits(circuit):
    target_tableau = get_target_tableau(circuit)
    loc, adj = jl.run_graph_sim_mini(circuit)
    vertices = list(zip(loc, adj))
    graph_tableau = get_stabilizer_tableau_from_vertices(vertices)

    assert_tableaus_correspond_to_the_same_stabilizer_state(
        graph_tableau, target_tableau
    )


@pytest.mark.parametrize(
    "filename",
    [
        "example_circuit.qasm",
    ],
)
def test_stabilizer_states_are_the_same_for_circuits(filename):
    # we want to repeat the experiment here since pyliqtr_transpile_to_clifford_t
    # is a random process.
    try:
        qiskit_circuit = import_from_qiskit(QuantumCircuit.from_qasm_file(filename))
    except FileNotFoundError:
        qiskit_circuit = import_from_qiskit(
            QuantumCircuit.from_qasm_file(os.path.join("examples", "data", filename))
        )

    circuit = transpile_to_native_gates(qiskit_circuit)
    test_circuit = get_icm(circuit)

    target_tableau = get_target_tableau(test_circuit)

    loc, adj = jl.run_graph_sim_mini(test_circuit)
    vertices = list(zip(loc, adj))
    graph_tableau = get_stabilizer_tableau_from_vertices(vertices)

    assert_tableaus_correspond_to_the_same_stabilizer_state(
        graph_tableau, target_tableau
    )


@pytest.mark.parametrize(
    "filename",
    [
        "single_rotation.qasm",
        "example_circuit.qasm",
    ],
)
def test_stabilizer_states_are_the_same_for_circuits_with_decomposed_rotations(
    filename,
):
    # we want to repeat the experiment here since pyliqtr_transpile_to_clifford_t
    # is a random process.
    try:
        qiskit_circuit = import_from_qiskit(QuantumCircuit.from_qasm_file(filename))
    except FileNotFoundError:
        qiskit_circuit = import_from_qiskit(
            QuantumCircuit.from_qasm_file(os.path.join("examples", "data", filename))
        )

    for i in range(1, 10):
        clifford_t = pyliqtr_transpile_to_clifford_t(
            qiskit_circuit, circuit_precision=10**-2
        )
        test_circuit = get_icm(clifford_t)

        target_tableau = get_target_tableau(test_circuit)

        loc, adj = jl.run_graph_sim_mini(test_circuit)
        vertices = list(zip(loc, adj))
        graph_tableau = get_stabilizer_tableau_from_vertices(vertices)

        assert_tableaus_correspond_to_the_same_stabilizer_state(
            graph_tableau, target_tableau
        )


# Everything below here is testing utils


def get_icm(circuit: Circuit, gates_to_decompose=["T", "T_Dagger", "RZ"]) -> Circuit:
    """Convert a circuit to the ICM form.

    Args:
        circuit (Circuit): the circuit to convert to ICM form
        gates_to_decompose (list, optional): list of gates to decompose into CNOT
        and adding ancilla qubits. Defaults to ["T", "T_Dagger"].

    Returns:
        Circuit: the circuit in ICM form
    """
    compiled_qubit_index = {i: i for i in range(circuit.n_qubits)}
    icm_circuit = []
    icm_circuit_n_qubits = circuit.n_qubits - 1
    for op in circuit.operations:
        compiled_qubits = [
            compiled_qubit_index.get(qubit, qubit) for qubit in op.qubit_indices
        ]

        if op.gate.name in gates_to_decompose:
            for original_qubit, compiled_qubit in zip(
                op.qubit_indices, compiled_qubits
            ):
                icm_circuit_n_qubits += 1
                compiled_qubit_index[original_qubit] = icm_circuit_n_qubits
                icm_circuit += [CNOT(compiled_qubit, icm_circuit_n_qubits)]
        elif op.gate.name == "RESET":
            for original_qubit, compiled_qubit in zip(
                op.qubit_indices, compiled_qubits
            ):
                icm_circuit_n_qubits += 1
                compiled_qubit_index[original_qubit] = icm_circuit_n_qubits
        else:
            icm_circuit += [
                op.gate(*[compiled_qubit_index[i] for i in op.qubit_indices])
            ]

    return Circuit(icm_circuit)


def get_target_tableau(circuit):
    sim = stim.TableauSimulator()
    for op in circuit.operations:
        if op.gate.name == "I":
            continue
        if op.gate.name == "X":
            sim.x(*op.qubit_indices)
        elif op.gate.name == "Y":
            sim.y(*op.qubit_indices)
        elif op.gate.name == "Z":
            sim.z(*op.qubit_indices)
        elif op.gate.name == "CNOT":
            sim.cx(*op.qubit_indices)
        elif op.gate.name == "S_Dagger":
            sim.s_dag(*op.qubit_indices)
        elif op.gate.name == "S":
            sim.s(*op.qubit_indices)
        elif op.gate.name == "SX":
            sim.sqrt_x(*op.qubit_indices)
        elif op.gate.name == "SX_Dagger":
            sim.sqrt_x_dag(*op.qubit_indices)
        elif op.gate.name == "H":
            sim.h(*op.qubit_indices)
        elif op.gate.name == "CZ":
            sim.cz(*op.qubit_indices)
        else:
            raise ValueError(f"Gate {op.gate.name} not supported.")
    return get_tableau_from_stim_simulator(sim)


def get_stabilizer_tableau_from_vertices(vertices):
    n_qubits = len(vertices)

    all_xs = np.identity(n_qubits, dtype=bool)
    all_zs = np.zeros((n_qubits, n_qubits), dtype=bool)

    for vertex_id, vertex in enumerate(vertices):
        for neighbor in vertex[1]:
            all_zs[neighbor, vertex_id] = True
            all_zs[vertex_id, neighbor] = True

    paulis = []
    for xs, zs in zip(all_xs, all_zs):
        paulis = paulis + [stim.PauliString.from_numpy(xs=xs, zs=zs)]

    sim = stim.TableauSimulator()
    tableau = stim.Tableau.from_stabilizers(paulis)
    sim.set_inverse_tableau(tableau.inverse())

    cliffords = []
    for vertex in vertices:
        # get vertex operations for each node in the tableau
        pauli_perm_class = vertex[0] - 1
        if pauli_perm_class == 0:
            cliffords += [[]]
        if pauli_perm_class == 1:
            cliffords += [["s"]]
        if pauli_perm_class == 2:
            cliffords += [["h"]]
        if pauli_perm_class == 3:
            cliffords += [["h", "s", "h"]]
        if pauli_perm_class == 4:
            cliffords += [["s", "h"]]
        if pauli_perm_class == 5:
            cliffords += [["h", "s"]]

    # perform the vertices operations on the tableau
    for i in range(n_qubits):
        for clifford in cliffords[i]:
            if clifford == "s":
                sim.s(i)
            elif clifford == "h":
                sim.h(i)

    return get_tableau_from_stim_simulator(sim)


def get_tableau_from_stim_simulator(sim):
    return np.column_stack(sim.current_inverse_tableau().inverse().to_numpy()[2:4])


def assert_tableaus_correspond_to_the_same_stabilizer_state(tableau_1, tableau_2):
    assert tableau_1.shape == tableau_2.shape

    n_qubits = len(tableau_2)

    # ensure that the graph tableau and the target tableau are composed
    # of paulis belonging to the same stabilizer group
    assert check_tableau_entries_commute

    # ensure that the stabilizers in the tableaus are linearly independent
    assert np.linalg.matrix_rank(tableau_1) == n_qubits
    assert np.linalg.matrix_rank(tableau_2) == n_qubits


@njit
def check_tableau_entries_commute(tableau_1, tableau_2):
    """Checks that the entries of two tableaus commute with each other.

    Args:
        tableau (np.array): tableau to check

    Returns:
        bool: true if the entries commute, false otherwise.
    """
    n_qubits = len(tableau_1) // 2

    for i in range(n_qubits):
        for j in range(i, n_qubits):
            if not commutes(tableau_1[i], tableau_2[j]):
                return False
    return True


@njit
def commutes(stab_1, stab_2):
    """Returns true if self commutes with other, otherwise false.

    Args:
        other (SymplecticPauli): SymplecticPauli for commutation

    Returns:
        bool: true if self and other commute, false otherwise.
    """
    n_qubits = len(stab_1) // 2
    comm1 = _bool_dot(stab_1[:n_qubits], stab_2[n_qubits:])
    comm2 = _bool_dot(stab_1[n_qubits:], stab_2[:n_qubits])
    return not (comm1 ^ comm2)


# numpy doesn't use the boolean binary ring when performing dot products
# https://github.com/numpy/numpy/issues/1456.
# So we define our own dot product which uses "xor" instead of "or" for addition.
@njit
def _bool_dot(x, y):
    array_and = np.logical_and(x, y)
    ans = array_and[0]
    for i in array_and[1:]:
        ans = np.logical_xor(ans, i)
    return ans
