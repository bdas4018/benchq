import os
from pathlib import Path

import pytest

from benchq.algorithms.time_evolution import _n_block_encodings_for_time_evolution
from benchq.problem_embeddings import get_qsp_program
from benchq.problem_ingestion import (
    generate_jw_qubit_hamiltonian_from_mol_data,
    get_hamiltonian_from_file,
    get_vlasov_hamiltonian,
)
from benchq.problem_ingestion.molecule_instance_generation import (
    generate_hydrogen_chain_instance,
)

SKIP_SLOW = pytest.mark.skipif(
    os.getenv("SLOW_BENCHMARKS") is None,
    reason="Slow benchmarks can only run if SLOW_BENCHMARKS env variable is defined",
)


def vlasov_test_case():
    k = 2.0
    alpha = 0.6
    nu = 0.0
    N = 2

    evolution_time = 5
    failure_tolerance = 1e-3

    operator = get_vlasov_hamiltonian(k, alpha, nu, N)

    n_block_encodings = _n_block_encodings_for_time_evolution(
        operator, evolution_time, failure_tolerance
    )

    return pytest.param(operator, n_block_encodings, id="vlasov")


def jw_test_case():
    evolution_time = 5
    failure_tolerance = 1e-3
    n_hydrogens = 2

    operator = generate_jw_qubit_hamiltonian_from_mol_data(
        generate_hydrogen_chain_instance(n_hydrogens)
    )

    n_block_encodings = _n_block_encodings_for_time_evolution(
        operator, evolution_time, failure_tolerance
    )

    return pytest.param(
        operator,
        n_block_encodings,
        id=f"jw-{n_hydrogens}",
    )


def fast_load_test_cases():
    def _load_hamiltonian(name):
        return get_hamiltonian_from_file(
            str(Path(__file__).parent / f"../examples/data/small_molecules/{name}.json")
        )

    evolution_time = 5
    failure_tolerance = 1e-3

    return [
        pytest.param(
            (operator := _load_hamiltonian(name)),
            _n_block_encodings_for_time_evolution(
                operator, evolution_time, failure_tolerance
            ),
            id=name,
            marks=SKIP_SLOW,
        )
        for name in (
            "C2H2-8-canonical_qubitop",
            "CH4-8-NOs_qubitop",
            "C2H4-12-NOs_qubitop",
        )
    ]


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "operator, n_block_encodings",
    [vlasov_test_case(), jw_test_case(), *fast_load_test_cases()],
)
def test_get_qsp_program(benchmark, operator, n_block_encodings):

    benchmark(get_qsp_program, operator, n_block_encodings)
