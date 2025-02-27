"""
Module for extending the Upwind, MPFA and MassMatrix discretizations in PorePy to handle
implicit Euler time-stepping. Flux terms are multiplied by time step and the mass term
has a rhs contribution from the previous time step.
See the parent discretizations for further documentation.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sps

import porepy as pp


class ImplicitMassMatrix(pp.MassMatrix):
    """
    Return rhs contribution based on the previous solution, which is stored in the
    pp.STATE field of the data dictionary.
    """

    def __init__(self, keyword="flow", variable="pressure"):
        """Set the discretization, with the keyword used for storing various
        information associated with the discretization. The time discretization also
        requires the previous solution, thus the variable needs to be specified.

        Parameters:
            keyword (str): Identifier of all information used for this
                discretization.
        """
        super().__init__(keyword)
        self.variable = variable

    def assemble_rhs(self, sd: pp.Grid, sd_data: dict):
        """Overwrite MassMatrix method to return the correct rhs for an IE time
        discretization, e.g. of the Biot problem.
        """
        matrix_dictionary = sd_data[pp.DISCRETIZATION_MATRICES][self.keyword]
        previous_solution = sd_data[pp.STATE][self.variable]

        return matrix_dictionary["mass"] * previous_solution


class ImplicitMpfa(pp.Mpfa):
    """
    Multiply all contributions by the time step.
    """

    def assemble_matrix_rhs(self, sd: pp.Grid, sd_data: dict):
        """Overwrite MPFA method to be consistent with the Biot dt convention."""
        a, b = super().assemble_matrix_rhs(sd, sd_data)
        dt = sd_data[pp.PARAMETERS][self.keyword]["time_step"]
        a = a * dt
        b = b * dt
        return a, b

    def assemble_int_bound_flux(
        self,
        sd: pp.Grid,
        sd_data: dict,
        intf: pp.MortarGrid,
        intf_data: dict,
        cc: np.ndarray,
        matrix: sps.spmatrix,
        rhs: np.ndarray,
        self_ind: int,
        use_secondary_proj: bool = False,
    ) -> None:
        """
        Overwrite the MPFA method to be consistent with the Biot dt convention
        """
        dt = sd_data[pp.PARAMETERS][self.keyword]["time_step"]

        div = sd.cell_faces.T

        bound_flux = sd_data[pp.DISCRETIZATION_MATRICES][self.keyword][
            self.bound_flux_matrix_key
        ]
        # Projection operators to grid
        if use_secondary_proj:
            proj = intf.mortar_to_secondary_int()
        else:
            proj = intf.mortar_to_primary_int()

        if sd.dim > 0 and bound_flux.shape[0] != sd.num_faces:
            # If bound flux is given as sub-faces we have to map it from sub-faces
            # to faces
            hf2f = pp.fvutils.map_hf_2_f(nd=1, sd=sd)
            bound_flux = hf2f * bound_flux
        if sd.dim > 0 and bound_flux.shape[1] != proj.shape[0]:
            raise ValueError(
                """Inconsistent shapes. Did you define a
            sub-face boundary condition but only a face-wise mortar?"""
            )

        cc[self_ind, 2] += dt * div * bound_flux * proj

    def assemble_int_bound_source(
        self,
        sd: pp.Grid,
        sd_data: dict,
        intf: pp.MortarGrid,
        intf_data: dict,
        cc: np.ndarray,
        matrix: sps.spmatrix,
        rhs: np.ndarray,
        self_ind: int,
    ) -> None:
        """Abstract method. Assemble the contribution from an internal
        boundary, manifested as a source term.

        The intended use is when the internal boundary is coupled to another
        node in a mixed-dimensional method. Specific usage depends on the
        interface condition between the nodes; this method will typically be
        used to impose flux continuity on a lower-dimensional domain.

        Implementations of this method will use an interplay between the grid on
        the node and the mortar grid on the relevant edge.

        Parameters:
            sd (pp.Grid): Grid which the condition should be imposed on.
            sd_data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            intf (pp.MortarGrid): interface
            intf_data (dict): Data dictionary for the interface in the
                mixed-dimensional grid.
            cc (block matrix, 3x3): Block matrix for the coupling condition.
                The first and second rows and columns are identified with the
                primary and secondary side; the third belongs to the edge variable.
                The discretization of the relevant term is done in-place in cc.
            matrix (block matrix 3x3): Discretization matrix for the edge and
                the two adjacent nodes.
            rhs (block_array 3x1): Right hand side contribution for the edge and
                the two adjacent nodes.
            self_ind (int): Index in cc and matrix associated with this node.
                Should be either 1 or 2.

        """
        proj = intf.mortar_to_secondary_int()
        dt = sd_data[pp.PARAMETERS][self.keyword]["time_step"]
        cc[self_ind, 2] -= proj * dt


class ImplicitTpfa(pp.Tpfa):
    """
    Multiply all contributions by the time step.

    Implementation note: This is a copy of ImplicitMpfa, modified to inherit from Tpfa.
    A unified implementation would have been preferable.

    """

    def assemble_matrix_rhs(self, sd: pp.Grid, sd_data: dict):
        """Overwrite MPFA method to be consistent with the Biot dt convention."""
        a, b = super().assemble_matrix_rhs(sd, sd_data)

        dt = sd_data[pp.PARAMETERS][self.keyword]["time_step"]
        a = a * dt
        b = b * dt
        return a, b

    def assemble_int_bound_flux(
        self,
        sd: pp.Grid,
        sd_data: dict,
        intf: pp.MortarGrid,
        intf_data: dict,
        cc: np.ndarray,
        matrix: sps.spmatrix,
        rhs: np.ndarray,
        self_ind: int,
        use_secondary_proj: bool = False,
    ) -> None:
        """
        Overwrite the MPFA method to be consistent with the Biot dt convention
        """
        dt = sd_data[pp.PARAMETERS][self.keyword]["time_step"]

        div = sd.cell_faces.T

        bound_flux = sd_data[pp.DISCRETIZATION_MATRICES][self.keyword]["bound_flux"]
        # Projection operators to grid
        if use_secondary_proj:
            proj = intf.mortar_to_secondary_int()
        else:
            proj = intf.mortar_to_primary_int()

        if sd.dim > 0 and bound_flux.shape[0] != sd.num_faces:
            # If bound flux is given as sub-faces we have to map it from sub-faces
            # to faces
            hf2f = pp.fvutils.map_hf_2_f(nd=1, sd=sd)
            bound_flux = hf2f * bound_flux
        if sd.dim > 0 and bound_flux.shape[1] != proj.shape[0]:
            raise ValueError(
                """Inconsistent shapes. Did you define a
            sub-face boundary condition but only a face-wise mortar?"""
            )

        cc[self_ind, 2] += dt * div * bound_flux * proj

    def assemble_int_bound_source(
        self,
        sd: pp.Grid,
        sd_data: dict,
        intf: pp.MortarGrid,
        intf_data: dict,
        cc: np.ndarray,
        matrix: sps.spmatrix,
        rhs: np.ndarray,
        self_ind: int,
    ) -> None:
        """Abstract method. Assemble the contribution from an internal
        boundary, manifested as a source term.

        The intended use is when the internal boundary is coupled to another
        node in a mixed-dimensional method. Specific usage depends on the
        interface condition between the nodes; this method will typically be
        used to impose flux continuity on a lower-dimensional domain.

        Implementations of this method will use an interplay between the grid on
        the node and the mortar grid on the relevant edge.

        Parameters:
            sd (pp.Grid): Grid which the condition should be imposed on.
            sd_data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            intf (pp.MortarGrid): interface
            intf_data (dictionary): Data dictionary for the edge in the
                mixed-dimensional grid.
            cc (block matrix, 3x3): Block matrix for the coupling condition.
                The first and second rows and columns are identified with the
                primary and secondary side; the third belongs to the edge variable.
                The discretization of the relevant term is done in-place in cc.
            matrix (block matrix 3x3): Discretization matrix for the edge and
                the two adjacent nodes.
            rhs (block_array 3x1): Right-hand side contribution for the edge and
                the two adjacent nodes.
            self_ind (int): Index in cc and matrix associated with this node.
                Should be either 1 or 2.

        """
        proj = intf.mortar_to_secondary_int()
        dt = sd_data[pp.PARAMETERS][self.keyword]["time_step"]
        cc[self_ind, 2] -= proj * dt


class ImplicitUpwind(pp.Upwind):
    """
    Multiply all contributions by the time step and advection weight.
    The latter may be a scalar or cell-wise values, in which case the upwind
    value is used. Note that the interior cell value is taken for BCs,
    regardless of the direction of the flux on the boundary.
    """

    def assemble_matrix_rhs(
        self, sd: pp.Grid, sd_data: dict
    ) -> tuple[sps.spmatrix, np.ndarray]:
        if sd.dim == 0:
            sd_data["flow_faces"] = sps.csr_matrix([0.0])
            return sps.csr_matrix([0.0]), np.array([0.0])

        parameter_dictionary = sd_data[pp.PARAMETERS]
        dt = parameter_dictionary[self.keyword]["time_step"]
        # Obtain the cell-wise advection weights
        w = (
            parameter_dictionary.expand_scalars(
                sd.num_cells, self.keyword, ["advection_weight"]
            )[0]
            * dt
        )
        a, b = super().assemble_matrix_rhs(sd, sd_data)
        a = a * sps.diags(w)
        b = b * sps.diags(w)
        return a, b


class ImplicitUpwindCoupling(pp.UpwindCoupling):
    """
    Multiply the advective mortar fluxes by the time step and advection weight.
    """

    def assemble_matrix_rhs(
        self,
        sd_primary: pp.Grid,
        sd_secondary: pp.Grid,
        intf: pp.MortarGrid,
        sd_data_primary: dict,
        sd_data_secondary: dict,
        intf_data: dict,
        matrix: sps.spmatrix,
    ) -> tuple[sps.spmatrix, np.ndarray]:
        """
        Construct the matrix (and right-hand side) for the coupling conditions.
        Note: the right-hand side is not implemented now.

        Parameters:
            sd_primary (pp.Grid): grid of higher dimension
            sd_secondary (pp.Grid): grid of lower dimension
            intf (pp.MortarGrid): interface
            sd_data_primary (dict): dictionary which stores the data for the higher
                dimensional grid
            sd_data_secondary (dict): dictionary which stores the data for the lower
                dimensional grid
            intf_data (dict): dictionary which stores the data for the edges of the
                grid bucket
            matrix: Uncoupled discretization matrix.

        Returns:
            cc: block matrix which store the contribution of the coupling
                condition. See the abstract coupling class for a more detailed
                description.
        """

        # Normal component of the velocity from the higher dimensional grid

        # @ALL: This should perhaps be defined by a globalized keyword
        parameter_dictionary_primary = sd_data_primary[pp.PARAMETERS]
        parameter_dictionary_secondary = sd_data_secondary[pp.PARAMETERS]
        lam_flux = intf_data[pp.PARAMETERS][self.keyword]["darcy_flux"]
        dt = parameter_dictionary_primary[self.keyword]["time_step"]
        w_primary = (
            parameter_dictionary_primary.expand_scalars(
                sd_primary.num_cells, self.keyword, ["advection_weight"]
            )[0]
            * dt
        )
        w_secondary = (
            parameter_dictionary_secondary.expand_scalars(
                sd_secondary.num_cells, self.keyword, ["advection_weight"]
            )[0]
            * dt
        )
        # Retrieve the number of degrees of both grids
        # Create the block matrix for the contributions

        # We know the number of dofs from the primary and secondary side from their
        # discretizations
        dof = np.array([matrix[0, 0].shape[1], matrix[1, 1].shape[1], intf.num_cells])
        cc = np.array([sps.coo_matrix((i, j)) for i in dof for j in dof])
        cc = cc.reshape((3, 3))

        # Projection from mortar to upper dimensional faces
        hat_P_avg = intf.primary_to_mortar_avg()
        # Projection from mortar to lower dimensional cells
        check_P_avg = intf.secondary_to_mortar_avg()

        # mapping from upper dim cells to faces
        # The mortars always points from upper to lower, so we don't flip any
        # signs
        div = np.abs(pp.numerics.fv.fvutils.scalar_divergence(sd_primary))

        # Find upwind weighting. if flag is True we use the upper weights
        # if flag is False we use the lower weighs
        flag = (lam_flux > 0).astype(float)
        not_flag = 1 - flag

        # assemble matrices
        # Transport out of upper equals lambda
        cc[0, 2] = div * hat_P_avg.T

        # transport out of lower is -lambda
        cc[1, 2] = -check_P_avg.T

        # Discretization of mortars
        # CHANGE from UpwindCoupling: multiply the discretization of the advective
        # mortar fluxes by dt and advection weight (e.g. heat capacity)

        # If fluid flux(lam_flux) is positive we use the upper value as weight,
        # i.e., T_primaryat * fluid_flux = lambda.
        # We set cc[2, 0] = T_primaryat * fluid_flux
        cc[2, 0] = sps.diags(lam_flux * flag) * hat_P_avg * div.T * sps.diags(w_primary)

        # If fluid flux is negative we use the lower value as weight,
        # i.e., T_check * fluid_flux = lambda.
        # we set cc[2, 1] = T_check * fluid_flux
        cc[2, 1] = sps.diags(lam_flux * not_flag) * check_P_avg * sps.diags(w_secondary)

        # The rhs of T * fluid_flux = lambda
        # Recover the information for the grid-grid mapping
        cc[2, 2] = -sps.eye(intf.num_cells)

        if sd_primary == sd_secondary:
            # All contributions to be returned to the same block of the
            # global matrix in this case
            cc = np.array([np.sum(cc, axis=(0, 1))])

        # rhs is zero
        rhs = np.squeeze([np.zeros(dof[0]), np.zeros(dof[1]), np.zeros(dof[2])])
        matrix += cc
        return matrix, rhs
