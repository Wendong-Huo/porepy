"""
Implementation of Terzaghi's consolidation problem.

Terzaghi's problem is a well known one-dimensional poroelastic problem [1 - 3].
Generally, when soils are subjected to a vertical load, porosity decreases, resulting
in less available space for pore water. The liquid within the pores can be expelled,
however, in certain types of soils (especially clayey soils) this process may take
some time due to their low permeability. This process is referred to as consolidation.

We consider a soil column of height `h`, where a constant load `F` is applied to the
top of the column while keeping the bottom impervious to flow. The exerted load will
cause an instantaneous rise in the fluid pressure, which will be equal to the applied
load. After that, the fluid pressure will monotonically decrease towards zero.

Even though Terzaghi's consolidation problem is strictly speaking one-dimensional, the
implemented setup employs a two-dimensional Cartesian grid with roller boundary
conditions for the mechanical subproblem and no-flux boundary conditions for the flow
subproblem on the sides of the domain such that the one-dimensional process can be
emulated.

The reason why we need to employ a two-dimensional grid is because PorePy only supports
Neumann boundary conditions for the discretization of the elasticity equations in
one-dimensional subdomains.

References:

    - [1] von Terzaghi, K. (1923). Die berechnung der durchassigkeitsziffer des tones
      aus dem verlauf der hydrodynamischen spannungs. erscheinungen. Sitzungsber. Akad.
      Wiss. Math. Naturwiss. Kl. Abt. 2A, 132, 105-124.

    - [2] von Terzaghi, K. (1944). Theoretical Soil Mechanics.

    - [3] Verruijt, A. (2017). An Introduction to Soil Mechanics (Vol. 30). Springer.

"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import matplotlib.colors as mcolors  # type: ignore
import matplotlib.pyplot as plt
import numpy as np

import porepy as pp
import porepy.models.fluid_mass_balance as mass
import porepy.models.poromechanics as poromechanics
from porepy.applications.derived_models.biot import BiotPoromechanics
from porepy.applications.verification_setups.verification_utils import (
    VerificationDataSaving,
    VerificationUtils,
)

# PorePy typings
number = pp.number
grid = pp.GridLike

# Physical parameters for the verification setup
terzaghi_solid_constants: dict[str, number] = {
    "lame_lambda": 1.65e9,  # [Pa]
    "shear_modulus": 1.475e9,  # [Pa]
    "specific_storage": 0,  # [Pa * m^-1]
    "permeability": 9.86e-14,  # [m^2]
}

terzaghi_fluid_constants: dict[str, number] = {
    "viscosity": 1e-3,  # [Pa * s]
    "density": 1e3,  # [kg * m^-3]
}


# -----> Data-saving
@dataclass
class TerzaghiSaveData:
    """Data class to save relevant results from the verification setup."""

    approx_displacement: np.ndarray
    """Numerical displacement."""

    approx_pressure: np.ndarray
    """Numerical pressure."""

    exact_pressure: np.ndarray
    """Exact pressure."""

    error_pressure: np.ndarray
    """L2-discrete relative error for the pressure."""

    approx_consolidation_degree: number
    """Numerical degree of consolidation."""

    error_consolidation_degree: number
    """Absolute error in the degree of consolidation."""

    exact_consolidation_degree: number
    """Exact degree of consolidation."""

    time: number
    """Current simulation time."""


class TerzaghiDataSaving(VerificationDataSaving):
    """Mixin class to save relevant data."""

    exact_sol: TerzaghiExactSolution
    """Exact solution object."""

    displacement: Callable[[list[pp.Grid]], pp.ad.MixedDimensionalVariable]
    """Displacement variable. Normally defined in a mixin instance of
    :class:`~porepy.models.momentum_balance.VariablesMomentumBalance`.

    """

    pressure: Callable[[list[pp.Grid]], pp.ad.MixedDimensionalVariable]
    """Pressure variable. Normally defined in a mixin instance of
    :class:`~porepy.models.fluid_mass_balance.VariablesSinglePhaseFlow`.

    """

    nondim_time: Callable[[number], number]
    """Method that non-dimensionalizes time. The method is provided by the mixin class
    :class:`TerzaghiUtils`.

    """

    nondim_length: Callable[[np.ndarray], np.ndarray]
    """Method that non-dimensionalises length. The method is provided by the mixin
    class :class:`TerzaghiUtils`.

    """

    nondim_pressure: Callable[[np.ndarray], np.ndarray]
    """Method that non-dimensionalises pressure. The method is provided by the mixin
    class :class:`TerzaghiUtils`.

    """

    numerical_consolidation_degree: Callable[[np.ndarray, np.ndarray], number]
    """Method that computes the numerical degree of consolidation. The method is
    provided by the mixin class :class:`TerzaghiUtils`.

    """

    def collect_data(self) -> TerzaghiSaveData:
        """Collect data for the current simulation time.

        Returns:
            TerzaghiSaveData object containing the results of the verification.

        """

        sd = self.mdg.subdomains()[0]
        t = self.time_manager.time

        # Collect data
        exact_pressure = self.exact_sol.pressure(sd.cell_centers[1], t)
        pressure_ad = self.pressure([sd])
        approx_pressure = pressure_ad.evaluate(self.equation_system).val
        error_pressure = self.relative_l2_error(
            grid=sd,
            true_array=exact_pressure,
            approx_array=approx_pressure,
            is_scalar=True,
            is_cc=True,
        )

        displacement_ad = self.displacement([sd])
        approx_displacement = displacement_ad.evaluate(self.equation_system).val

        approx_consolidation_degree = self.numerical_consolidation_degree(
            approx_displacement,
            approx_pressure,
        )
        exact_consolidation_degree = self.exact_sol.consolidation_degree(t)
        error_consolidation_degree = np.abs(
            approx_consolidation_degree - exact_consolidation_degree
        )

        # Store collected data in data class
        collected_data = TerzaghiSaveData(
            approx_displacement=approx_displacement,
            approx_pressure=approx_pressure,
            error_pressure=error_pressure,
            exact_pressure=exact_pressure,
            approx_consolidation_degree=approx_consolidation_degree,
            error_consolidation_degree=error_consolidation_degree,
            exact_consolidation_degree=exact_consolidation_degree,
            time=t,
        )

        return collected_data


# -----> Exact solution
class TerzaghiExactSolution:
    """Class containing exact solutions to Terzaghi's consolidation problem."""

    def __init__(self, setup):
        """Constructor of the class"""
        self.setup = setup

    def pressure(self, y: np.ndarray, t: number) -> np.ndarray:
        """Compute exact pressure.

        Parameters:
            y: vertical coordinates [m].
            t: Time [s].

        Returns:
            Exact pressure profile for the given time ``t``.

        """

        F = self.setup.params.get("vertical_load", 6e8)
        nondim_y = self.setup.nondim_length(y)
        nondim_t = self.setup.nondim_time(t)

        n = self.setup.params.get("upper_limit_summation", 1000)

        if t == 0:  # initially, the pressure equals the vertical load
            p = F * np.ones_like(y)
        else:
            sum_series = np.zeros_like(y)
            for i in range(1, n + 1):
                sum_series += (
                    (((-1) ** (i - 1)) / (2 * i - 1))
                    * np.cos((2 * i - 1) * (np.pi / 2) * nondim_y)
                    * np.exp((-((2 * i - 1) ** 2)) * (np.pi**2 / 4) * nondim_t)
                )
            p = (4 / np.pi) * F * sum_series

        return p

    def consolidation_degree(self, t: number) -> float:
        """Compute exact degree of consolidation.

        Parameters:
            t: Time [s].

        Returns:
            Degree of consolidation for the given time `t`.

        """
        t_nondim = self.setup.nondim_time(t)
        n = self.setup.params.get("upper_limit_summation", 1000)

        if t == 0:  # initially, the soil is unconsolidated
            deg_cons = 0.0
        else:
            sum_series = 0
            for i in range(1, n + 1):
                sum_series += (
                    1
                    / ((2 * i - 1) ** 2)
                    * np.exp(-((2 * i - 1) ** 2) * (np.pi**2 / 4) * t_nondim)
                )
            deg_cons = 1 - (8 / (np.pi**2)) * sum_series

        return deg_cons


# -----> Utilities
class TerzaghiUtils(VerificationUtils):
    """Mixin class containing useful utility methods for the setup."""

    params: dict
    """Setup parameters dictionary."""

    mdg: pp.MixedDimensionalGrid
    """Mixed-dimensional grid. Only one subdomain for this verification."""

    time_manager: pp.TimeManager
    """Time-stepping object."""

    stress_keyword: str
    """Key for accessing data parameters for the mechanics subproblem."""

    bc_values_mechanics_key: str
    """Key for accessing mechanical boundary values."""

    solid: pp.SolidConstants
    """Solid constant object."""

    fluid: pp.FluidConstants
    """Fluid constant object."""

    exact_sol: TerzaghiExactSolution
    """Exact solution object."""

    results: list[TerzaghiSaveData]
    """List of :class:`TerzaghiSaveData` objects containing the results of the
    verification.

    """

    # ---> Derived physical quantities
    def confined_compressibility(self) -> number:
        """Compute confined compressibility [Pa^-1].

        Returns:
            Confined compressibility.

        """
        mu_s = self.solid.shear_modulus()
        lambda_s = self.solid.lame_lambda()
        m_v = 1 / (2 * mu_s + lambda_s)
        return m_v

    def consolidation_coefficient(self) -> number:
        """Compute consolidation coefficient [m^2 * s^-1].

        Returns:
            Coefficient of consolidation.

        """
        k = self.solid.permeability()  # [m^2]
        mu_f = self.fluid.viscosity()  # [Pa * s]
        rho = self.fluid.density()  # [kg * m^-3]
        gamma_f = rho * pp.GRAVITY_ACCELERATION  # specific weight [Pa * m^-1]
        hydraulic_conductivity = (k * gamma_f) / mu_f  # [m * s^-1]
        storage = self.solid.specific_storage()  # [Pa^-1]
        alpha_biot = self.solid.biot_coefficient()  # [-]
        m_v = self.confined_compressibility()  # [Pa^-1]
        c_v = hydraulic_conductivity / (gamma_f * (storage + alpha_biot**2 * m_v))

        return c_v

    # ---> Non-dimensionalization methods
    def nondim_time(self, t: number) -> number:
        """Non-dimensional time.

        Parameters:
            t: Time in seconds.

        Returns:
            Dimensionless time.

        """
        h = self.params.get("height", 1.0)  # [m]
        c_v = self.consolidation_coefficient()  # [m * s^2]

        return (t * c_v) / (h**2)

    def nondim_length(self, length: np.ndarray) -> np.ndarray:
        """Non-dimensional length.

        Parameters:
            length: Length in meters.

        Returns:
            Non-dimensionalized length.

        """
        return length / self.params.get("height", 1.0)

    def nondim_pressure(self, pressure: np.ndarray) -> np.ndarray:
        """Nondimensional pressure.

        Parameters:
            pressure: Fluid pressure in Pa.

        Returns:
            Non-dimensional pressure.

        """
        return pressure / np.abs(self.params.get("vertical_load", 6e8))

    # ---> Postprocessing methods
    # TODO: Consider moving this method to a place where can be reused.
    def displacement_trace(
        self, displacement: np.ndarray, pressure: np.ndarray
    ) -> np.ndarray:
        """Project the displacement vector onto the faces.

        Parameters:
            displacement: displacement solution of shape (sd.dim * sd.num_cells, ).
            pressure: pressure solution of shape (sd.num_cells, ).

        Returns:
            Trace of the displacement with shape (sd.dim * sd.num_faces, ).

        """
        # Rename arguments
        u = displacement
        p = pressure

        # Discretization matrices
        sd = self.mdg.subdomains()[0]
        data = self.mdg.subdomain_data(sd)
        discr = data[pp.DISCRETIZATION_MATRICES][self.stress_keyword]
        bound_u_cell = discr["bound_displacement_cell"]
        bound_u_face = discr["bound_displacement_face"]
        bound_u_pressure = discr["bound_displacement_pressure"]

        # Mechanical boundary values
        bc_vals = data[pp.STATE][self.bc_values_mechanics_key]

        # Compute trace of the displacement
        trace_u = bound_u_cell * u + bound_u_face * bc_vals + bound_u_pressure * p

        return trace_u

    def numerical_consolidation_degree(
        self, displacement: np.ndarray, pressure: np.ndarray
    ) -> number:
        """Numerical consolidation degree.

        Parameters:
            displacement: Displacement solution of shape (sd.dim * sd.num_cells, ).
            pressure: Pressure solution of shape (sd.num_cells, ).

        Returns:
            Numerical degree of consolidation.

        """
        sd = self.mdg.subdomains()[0]
        h = self.params.get("height", 1.0)
        m_v = self.confined_compressibility()
        vertical_load = self.params.get("vertical_load", 6e8)
        t = self.time_manager.time

        if t == 0:  # initially, the soil is unconsolidated
            consol_deg = 0.0
        else:
            trace_u = self.displacement_trace(displacement, pressure)
            u_inf = m_v * h * vertical_load
            u_0 = 0
            u = np.max(np.abs(trace_u[1 :: sd.dim]))
            consol_deg = (u - u_0) / (u_inf - u_0)

        return consol_deg

    # ---> Methods related to plotting
    def plot_results(self) -> None:
        """Plotting the results."""
        cmap = mcolors.ListedColormap(plt.cm.tab20.colors[: len(self.results)])
        self._pressure_plot(color_map=cmap)
        self._consolidation_degree_plot(color_map=cmap)

    def _pressure_plot(self, color_map: mcolors.ListedColormap) -> None:
        """Plot non-dimensional pressure profiles.

        Parameters:
            color_map: listed color map object.

        """

        sd = self.mdg.subdomains()[0]
        nondim_vertical_coo = self.nondim_length(sd.cell_centers[1])

        fig, ax = plt.subplots(figsize=(9, 8))
        y_ex = np.linspace(0, self.params.get("height", 1.0), 400)
        t = self.time_manager.time
        for idx, result in enumerate(self.results):
            ax.plot(
                self.nondim_pressure(self.exact_sol.pressure(y=y_ex, t=t)),
                self.nondim_length(y_ex),
                color=color_map.colors[idx],
            )
            ax.plot(
                self.nondim_pressure(np.array(result.approx_pressure)),
                nondim_vertical_coo,
                color=color_map.colors[idx],
                linewidth=0,
                marker=".",
                markersize=8,
            )
            ax.plot(
                [],
                [],
                color=color_map.colors[idx],
                linewidth=0,
                marker="s",
                markersize=12,
                label=rf"$t=${np.round(t, 4)}",
            )

        ax.set_xlabel(r"Non-dimensional pressure, $p/p_0$", fontsize=15)
        ax.set_ylabel(r"Non-dimensional height, $y/h$", fontsize=15)
        ax.legend(loc="center right", bbox_to_anchor=(1.4, 0.5), fontsize=13)
        ax.grid()
        plt.subplots_adjust(right=0.7)
        plt.show()

    def _consolidation_degree_plot(self, color_map: mcolors.ListedColormap) -> None:
        """Plot the degree of consolidation versus non-dimensional time.

        Parameters:
            color_map: listed color map object.

        """

        # Retrieve data
        t_ex = np.linspace(
            self.time_manager.time_init, self.time_manager.time_final, 400
        )
        nondim_t_ex = np.asarray([self.nondim_time(t) for t in t_ex])
        exact_consolidation = np.asarray(
            [self.exact_sol.consolidation_degree(t) for t in t_ex]
        )

        nondim_t = np.asarray(
            [self.nondim_time(t) for t in self.time_manager.schedule[1:]]
        )
        numerical_consolidation = np.asarray(
            [result.approx_consolidation_degree for result in self.results]
        )

        fig, ax = plt.subplots(figsize=(9, 8))
        ax.semilogx(
            nondim_t_ex, exact_consolidation, color=color_map.colors[0], label="Exact"
        )
        ax.semilogx(
            nondim_t,
            numerical_consolidation,
            color=color_map.colors[0],
            linewidth=0,
            marker=".",
            markersize=12,
            label="Numerical",
        )
        ax.set_xlabel(r"Non-dimensional time, $t\,c_f\,h^{-2}$", fontsize=15)
        ax.set_ylabel(r"Degree of consolidtaion, $U(t)$", fontsize=15)
        ax.legend(fontsize=14)
        ax.grid()
        plt.show()


# -----> Geometry
class PseudoOneDimensionalColumn(pp.ModelGeometry):
    """Define geometry of the verification setup."""

    params: dict
    """Simulation model parameters."""

    def set_md_grid(self) -> None:
        """Create the mixed-dimensional grid based on two-dimensional Cartesian grid."""
        height = self.params.get("height", 1.0)  # [m]
        num_cells = self.params.get("num_cells", 20)
        ls = 1 / self.units.m
        phys_dims = np.array([height, height]) * ls
        n_cells = np.array([1, num_cells])
        self.domain_bounds = pp.geometry.bounding_box.from_points(
            np.array([[0, 0], phys_dims]).T
        )
        sd: pp.Grid = pp.CartGrid(n_cells, phys_dims)
        sd.compute_geometry()
        self.mdg = pp.meshing.subdomains_to_mdg([[sd]])


# -----> Boundary conditions
class TerzaghiBoundaryConditionsMechanicsTimeDependent(
    poromechanics.BoundaryConditionsMechanicsTimeDependent,
):
    mdg: pp.MixedDimensionalGrid
    """Mixed-dimensional grid."""

    domain_boundary_sides: Callable[[pp.Grid], pp.bounding_box.DomainSides]
    """Named tuple containing the boundary sides indices."""

    stress_keyword: str
    """Keyword for the mechanical subproblem."""

    bc_values_mechanics_key: str
    """Keyword for accessing the boundary values for the mechanical subproblem."""

    params: dict
    """Parameter dictionary of the verification setup."""

    def bc_type_mechanics(self, sd: pp.Grid) -> pp.BoundaryConditionVectorial:
        """Define type of boundary conditions.

        Parameters:
            sd: Subdomain grid.

        Returns:
            bc: Boundary condition representation. Neumann on the North, Dirichlet on
            the South, and rollers on the sides.

        """
        # Inherit bc from parent class. This sets all bc faces as Dirichlet.
        bc = super().bc_type_mechanics(sd=sd)

        # Get boundary sides, retrieve data dict, and bc object
        _, east, west, north, *_ = self.domain_boundary_sides(sd)

        # East side: Roller
        bc.is_neu[1, east] = True
        bc.is_dir[1, east] = False

        # West side: Roller
        bc.is_neu[1, west] = True
        bc.is_dir[1, west] = False

        # North side: Neumann
        bc.is_neu[:, north] = True
        bc.is_dir[:, north] = False

        # South side: Dirichlet (already set thanks to inheritance)

        return bc

    def time_dependent_bc_values_mechanics(
        self, subdomains: list[pp.Grid]
    ) -> np.ndarray:
        """Boundary values for mechanics.

        Parameters:
            subdomains: List of subdomains on which to define boundary conditions.

        Returns:
            Array of boundary values. Only non-zero values are the ones associated to
              the North side of the domain.

        """
        sd = subdomains[0]
        vertical_load = self.params.get("vertical_load", 6e8)
        _, _, _, north, *_ = self.domain_boundary_sides(sd)
        bc_values = np.array([np.zeros(sd.num_faces), np.zeros(sd.num_faces)])
        bc_values[1, north] = -vertical_load * sd.face_areas[north]
        return bc_values.ravel("F")


class TerzaghiBoundaryConditionsSinglePhaseFlow(
    mass.BoundaryConditionsSinglePhaseFlow,
):

    domain_boundary_sides: Callable[[pp.Grid], pp.bounding_box.DomainSides]
    """Utility function containing the indices of the domain boundary sides."""

    def bc_type_darcy(self, sd: pp.Grid) -> pp.BoundaryCondition:
        """Define boundary condition types for the flow subproblem.

        Parameters:
            sd: Subdomain grid.

        Returns:
            Scalar boundary condition representation. All sides no flow, except the
            North side which is set to a constant pressure.

        """
        # Define boundary regions
        all_bf, _, _, north, *_ = self.domain_boundary_sides(sd)
        north_bc = np.isin(all_bf, np.where(north)).nonzero()

        # All sides Neumann, except the North which is Dirichlet
        bc_type = np.asarray(all_bf.size * ["neu"])
        bc_type[north_bc] = "dir"

        bc = pp.BoundaryCondition(sd, faces=all_bf, cond=list(bc_type))

        return bc


class TerzaghiPoromechanicsBoundaryConditions(
    TerzaghiBoundaryConditionsSinglePhaseFlow,
    TerzaghiBoundaryConditionsMechanicsTimeDependent,
):
    """Mixer class for poromechanics boundary conditions."""


# -----> Solution strategy
class TerzaghiSolutionStrategy(
    poromechanics.SolutionStrategyPoromechanics,
):
    exact_sol: TerzaghiExactSolution
    """Exact solution object."""

    plot_results: Callable
    """Method that plots the pressure and degree of consolidation."""

    results: list[TerzaghiSaveData]
    """List of :class:`TerzaghiSaveData` objects, containing the results of the
    verification.

    """

    def __init__(self, params: dict) -> None:
        """Constructor of the class.

        Parameters:
            params: Parameters of the verification setup.

        """
        super().__init__(params)

        self.exact_sol: TerzaghiExactSolution
        """Exact solution object"""

        self.results: list[TerzaghiSaveData] = []
        """List of stored results from the verification."""

    def set_materials(self):
        """Set material parameters.

        Add exact solution object to the simulation model after materials have been set.
        """
        super().set_materials()
        self.exact_sol = TerzaghiExactSolution(self)

        # Specific storage must be zero
        assert self.solid.specific_storage() == 0

        # Biot's coefficient must be one
        assert self.solid.biot_coefficient() == 1

    def initial_condition(self) -> None:
        """Set initial conditions.

        Terzaghi's problem assumes that the soil is initially unconsolidated and that
        the initial fluid pressure equals the vertical load.

        """
        super().initial_condition()
        # Since the parent class sets zero initial displacement, we only need to
        # modify the initial conditions for the flow subproblem.
        sd = self.mdg.subdomains()[0]
        data = self.mdg.subdomain_data(sd)
        vertical_load = self.params.get("vertical_load", 6e8)
        initial_p = vertical_load * np.ones(sd.num_cells)
        data[pp.STATE][self.pressure_variable] = initial_p
        data[pp.STATE][pp.ITERATE][self.pressure_variable] = initial_p

    def after_simulation(self) -> None:
        """Method to be called after the simulation has finished."""
        if self.params.get("plot_results", False):
            self.plot_results()

    def _is_nonlinear_problem(self) -> bool:
        """The problem is linear."""
        return False


class TerzaghiSetup(  # type: ignore[misc]
    PseudoOneDimensionalColumn,
    TerzaghiPoromechanicsBoundaryConditions,
    TerzaghiSolutionStrategy,
    TerzaghiUtils,
    TerzaghiDataSaving,
    BiotPoromechanics,
):
    """Mixer class for Terzaghi's consolidation problem."""
