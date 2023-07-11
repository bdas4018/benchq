################################################################################
# © Copyright 2023 Zapata Computing Inc.
################################################################################
from typing import Tuple

import numpy as np
import datetime
from openfermion.resource_estimates import sf

from benchq.resource_estimation.of_modified import (
    AlgorithmParameters,
    CostEstimate,
    cost_estimator,
)
from benchq.data_structures.resource_info import OpenFermionResourceInfo
from benchq.resource_estimation._compute_lambda_sf import compute_lambda

from openfermion.resource_estimates.molecule import pyscf_to_cas

from benchq.problem_ingestion.molecule_instance_generation import (
    generate_hydrogen_chain_instance,
)


def get_single_factorized_qpe_toffoli_and_qubit_cost(
    h1: np.ndarray,
    eri: np.ndarray,
    rank: int,
    allowable_phase_estimation_error: float,
    bits_precision_state_prep: float,
) -> Tuple[int, int]:
    """Get the number of Toffoli gates and logical qubits for single factorized QPE.

    See get_single_factorized_qpe_resource_estimate for descriptions of arguments.

    Returns:
        The number of Toffoli gates and logical qubits.
    """
    num_orb = h1.shape[0]
    num_spinorb = num_orb * 2

    # First, up: lambda and CCSD(T)
    eri_rr, LR = sf.factorize(eri, rank)
    lam = compute_lambda(h1, eri_rr, LR)

    # now do costing
    stps1 = sf.compute_cost(
        num_spinorb,
        lam,
        allowable_phase_estimation_error,
        L=rank,
        chi=bits_precision_state_prep,
        stps=20000,
    )[0]

    _, sf_total_toffoli_cost, sf_logical_qubits = sf.compute_cost(
        num_spinorb,
        lam,
        allowable_phase_estimation_error,
        L=rank,
        chi=bits_precision_state_prep,
        stps=stps1,
    )
    return sf_total_toffoli_cost, sf_logical_qubits


def get_single_factorized_qpe_resource_estimate(
    h1: np.ndarray,
    eri: np.ndarray,
    rank: int,
    surface_code_cycle_time: datetime.timedelta = datetime.timedelta(microseconds=1),
    allowable_phase_estimation_error: float = 0.001,
    bits_precision_state_prep: int = 10,
) -> OpenFermionResourceInfo:
    """Get the estimated resources for single factorized QPE as described in PRX Quantum
    2, 030305.

    Args:
        h1 (np.ndarray): Matrix elements of the one-body operator that includes kinetic
            energy operator and electorn-nuclear Coulomb operator.
        eri (np.ndarray): Four-dimensional array containing electron-repulsion
            integrals.
        rank (int): Rank of the factorization.
        allowable_phase_estimation_error (float): Allowable error in phase estimation.
            Corresponds to epsilon_QPE in the paper.
        bits_precision_state_prep (float): The number of bits for the representation of
            the coefficients. Corresponds to aleph_1 and aleph_2 in the paper.

    Returns:
        A dictionary containing the estimated time and physical qubit requirements.
    """

    if not np.allclose(np.transpose(eri, (2, 3, 0, 1)), eri):
        raise ValueError("ERI do not have (ij | kl) == (kl | ij) symmetry.")

    (
        sf_total_toffoli_cost,
        sf_logical_qubits,
    ) = get_single_factorized_qpe_toffoli_and_qubit_cost(
        h1, eri, rank, allowable_phase_estimation_error, bits_precision_state_prep
    )
    print("Number of Toffoli's is:", sf_total_toffoli_cost)
    print("Number of logical qubits is:", sf_logical_qubits)

    # Model physical costs
    best_cost, best_params = cost_estimator(
        sf_logical_qubits,
        sf_total_toffoli_cost,
        surface_code_cycle_time=surface_code_cycle_time,
        physical_error_rate=1.0e-3,
        portion_of_bounding_box=1.0,
    )

    return _openfermion_result_to_resource_info(best_cost, best_params)


def _openfermion_result_to_resource_info(
    cost: CostEstimate, algorithm_parameters: AlgorithmParameters
) -> OpenFermionResourceInfo:
    return OpenFermionResourceInfo(
        n_physical_qubits=cost.physical_qubit_count,
        n_logical_qubits=algorithm_parameters.max_allocated_logical_qubits,
        total_time_in_seconds=cost.duration.seconds,
        code_distance=algorithm_parameters.logical_data_qubit_distance,
        logical_error_rate=cost.algorithm_failure_probability,
        decoder_info=None,
        widget_name=algorithm_parameters.magic_state_factory.details,
        extra=algorithm_parameters,
    )
