"""
Module contains common functionalities for discretization based on the mixed
variational formulation.
"""
from __future__ import annotations

from typing import Optional
from warnings import warn

import numpy as np
import scipy.sparse as sps

import porepy as pp
from porepy.numerics.interface_laws.elliptic_discretization import (
    EllipticDiscretization,
)


def project_flux(
    mdg: pp.MixedDimensionalGrid,
    discr,
    flux: str,
    P0_flux: np.ndarray,
    mortar_key: str = "mortar_solution",
) -> None:
    """
    Save in the grid bucket a piece-wise vector representation of the flux
    for each grid.

    Parameters
    ---------
    mdg: the grid bucket
    discr: discretization class
    flux: identifier of the flux, already split, in the grid bucket
    P0_flux: identifier of the reconstructed flux which will be added to the grid bucket.
    mortar_key (optional): identifier of the mortar variable, already split, in the
        grid bucket. The default value is "mortar_solution".

    """

    for sd, data in mdg.subdomains(return_data=True):
        # we need to recover the flux from the mortar variable before
        # the projection, only lower dimensional edges need to be considered.
        edge_flux = np.zeros(data[pp.STATE][flux].size)
        faces = sd.tags["fracture_faces"]
        if np.any(faces):
            # recover the sign of the flux, since the mortar is assumed
            # to point from the higher to the lower dimensional problem
            _, indices = np.unique(sd.cell_faces.indices, return_index=True)
            sign = sps.diags(sd.cell_faces.data[indices], 0)

            for intf in mdg.subdomain_to_interfaces(sd):
                # do not consider the contribution from the mortar grid when the latter is
                # of the same dimension or codim > 1 (e.g., wells)
                if intf.dim == sd.dim or intf.codim > 1:
                    continue

                data_intf = mdg.interface_data(intf)
                # project the mortar variable back to the higher dimensional
                # problem
                # edge_flux += sign * g_m.mortar_to_primary_int() * d_e[pp.STATE][mortar_key]
                edge_flux += (
                    sign
                    * intf.primary_to_mortar_avg().T
                    * data_intf[pp.STATE][mortar_key]
                )

        data[pp.STATE][P0_flux] = discr.project_flux(
            sd, edge_flux + data[pp.STATE][flux], data
        )


class DualElliptic(EllipticDiscretization):
    """Parent class for methods based on the mixed variational form of the
    elliptic equation. The class should not be used by itself, but provides a
    sheared implementation of central methods.

    Known subclasses that can be used for actual discretization are MVEM and RT0.

    """

    def __init__(self, keyword: str, name: str) -> None:

        # Identify which parameters to use:
        self.keyword = keyword
        self.name = name

        # Keywords used to identify individual terms in the discretization matrix dictionary
        # Discretization of H_div mass matrix
        self.mass_matrix_key = "mass"
        # Discretization of divergence matrix
        self.div_matrix_key = "div"
        # Discretization of flux reconstruction
        self.vector_proj_key = "vector_proj"
        # Discretization of vector source terms (gravity)
        self.vector_source_key = "vector_source"

    def ndof(self, sd: pp.Grid) -> int:
        """Return the number of degrees of freedom associated to the method.

        Args:
            sd (pp.Grid): A grid.

        Returns:
            int: The number of degrees of freedom.

        """
        return sd.num_cells + sd.num_faces

    def assemble_matrix_rhs(
        self, sd: pp.Grid, data: dict
    ) -> tuple[sps.csr_matrix, np.ndarray]:
        """Return the matrix and right-hand side for a discretization of a second
        order elliptic equation.

        Args:
            sd (pp.Grid): Computational grid, with geometry fields computed.
            data (dictionary): With data stored.

        Returns:
            scipy.sparse.csr_matrix: System matrix of this discretization. The size of
                the matrix will depend on the specific discretization.
            np.ndarray: Right-hand side vector with representation of boundary
                conditions. The size of the vector will depend on the discretization.

        """
        # First assemble the matrix
        M = self.assemble_matrix(sd, data)

        # Impose Neumann and Robin boundary conditions, with appropriate scaling of the
        # diagonal element
        M, bc_weight = self.assemble_neumann_robin(sd, data, M, bc_weight=True)

        # Assemble right hand side term
        return M, self.assemble_rhs(sd, data, bc_weight)

    def assemble_matrix(self, g: pp.Grid, data: dict) -> sps.csr_matrix:
        """Assemble matrix from an existing discretization.

        Args:
            sd (pp.Grid): Computational grid, with geometry fields computed.
            data (dictionary): With data stored.

        Returns:
            scipy.sparse.csr_matrix: System matrix of this discretization. The
                size of the matrix will depend on the specific discretization.

        """
        matrix_dictionary = data[pp.DISCRETIZATION_MATRICES][self.keyword]

        mass = matrix_dictionary[self.mass_matrix_key]
        div = matrix_dictionary[self.div_matrix_key]
        return sps.bmat([[mass, div.T], [div, None]], format="csr")

    def assemble_neumann_robin(
        self, sd: pp.Grid, data: dict, M, bc_weight: bool = False
    ) -> tuple[sps.csr_matrix, int]:
        """Impose Neumann and Robin boundary discretization on an already assembled
        system matrix.
        """
        # Obtain the mass matrix
        matrix_dictionary = data[pp.DISCRETIZATION_MATRICES][self.keyword]

        mass = matrix_dictionary[self.mass_matrix_key]
        if mass.shape[0] == 0:
            norm = 1
        else:
            if bc_weight:
                norm = sps.linalg.norm(mass, np.inf)
            else:
                norm = 1

        bc = data[pp.PARAMETERS][self.keyword]["bc"]

        # For mixed discretizations, internal boundaries
        # are handled by assigning Dirichlet conditions. Thus, we remove them
        # from the is_neu and is_rob (where they belong by default) and add them in
        # is_dir.

        # assign the Neumann boundary conditions
        is_neu = np.logical_and(bc.is_neu, np.logical_not(bc.is_internal))
        if bc and np.any(is_neu):
            # it is assumed that the faces dof are put before the cell dof
            is_neu = np.where(is_neu)[0]

            # set in an efficient way the essential boundary conditions, by
            # clear the rows and put norm in the diagonal
            for row in is_neu:
                M.data[M.indptr[row] : M.indptr[row + 1]] = 0.0

            d = M.diagonal()
            d[is_neu] = norm
            M.setdiag(d)

        # assign the Robin boundary conditions
        is_rob = np.logical_and(bc.is_rob, np.logical_not(bc.is_internal))
        if bc and np.any(is_rob):
            # it is assumed that the faces dof are put before the cell dof
            is_rob = np.where(is_rob)[0]

            rob_val = np.zeros(self.ndof(sd))
            rob_val[is_rob] = 1.0 / (bc.robin_weight[is_rob] * sd.face_areas[is_rob])
            M += sps.dia_matrix((rob_val, 0), shape=(rob_val.size, rob_val.size))

        return M, norm

    def assemble_rhs(
        self, sd: pp.Grid, data: dict, bc_weight: float = 1.0
    ) -> np.ndarray:
        """Return the righ-hand side for a discretization of a second order elliptic
        equation.

        Args:
            sd (Grid): Computational grid, with geometry fields computed.
            data (dictionary): With data stored.
            bc_weight (float): to use the infinity norm of the matrix to impose the
                boundary conditions. Default 1.

        Returns:
            np.ndarray: Right hand side vector with representation of boundary
                conditions. The size of the vector will depend on the discretization.

        """
        # Allow short variable names in backend function
        # pylint: disable=invalid-name

        parameter_dictionary = data[pp.PARAMETERS][self.keyword]

        # Get dictionary for discretization matrix storage
        matrix_dictionary = data[pp.DISCRETIZATION_MATRICES][self.keyword]
        proj = matrix_dictionary[self.vector_proj_key]

        rhs = np.zeros(self.ndof(sd))
        if sd.dim == 0:
            return rhs

        bc = parameter_dictionary["bc"]
        bc_val = parameter_dictionary["bc_values"]

        assert not bool(bc is None) != bool(bc_val is None)

        # The vector source, defaults to zero if not specified.
        vector_source = parameter_dictionary.get(
            "vector_source", np.zeros(proj.shape[0])
        )
        # Discretization of the vector source term
        rhs[: sd.num_faces] += proj.T * vector_source

        if bc is None:
            return rhs

        # For mixed discretizations, internal boundaries
        # are handled by assigning Dirichlet conditions. Thus, we remove them
        # from the is_neu (where they belong by default). As the dirichlet
        # values are simply added to the rhs, and the internal Dirichlet
        # conditions on the fractures SHOULD be homogeneous, we exclude them
        # from the dirichlet condition as well.
        is_neu = np.logical_and(bc.is_neu, np.logical_not(bc.is_internal))
        is_dir = np.logical_and(bc.is_dir, np.logical_not(bc.is_internal))
        is_rob = np.logical_and(bc.is_rob, np.logical_not(bc.is_internal))
        if hasattr(sd, "periodic_face_map"):
            raise NotImplementedError(
                "Periodic boundary conditions are not implemented for DualElliptic"
            )

        faces, _, sign = sps.find(sd.cell_faces)
        sign = sign[np.unique(faces, return_index=True)[1]]

        if np.any(is_dir):
            is_dir = np.where(is_dir)[0]
            rhs[is_dir] += -sign[is_dir] * bc_val[is_dir]

        if np.any(is_rob):
            is_rob = np.where(is_rob)[0]
            rhs[is_rob] += -sign[is_rob] * bc_val[is_rob] / bc.robin_weight[is_rob]

        if np.any(is_neu):
            is_neu = np.where(is_neu)[0]
            rhs[is_neu] = sign[is_neu] * bc_weight * bc_val[is_neu]

        return rhs

    def project_flux(self, sd: pp.Grid, u: np.ndarray, data: dict) -> np.ndarray:
        """Project the velocity computed with a dual solver to obtain a
        piecewise constant vector field, one triplet for each cell.

        We assume the following two sub-dictionaries to be present in the data
        dictionary:
            matrix_dictionary, for storage of discretization matrices.
                Stored in data[pp.DISCRETIZATION_MATRICES][self.keyword]
                with matrix named self.vector_proj_key and constructed in the discretize
                method.

        Parameters
        ----------
        sd : grid, or a subclass, with geometry fields computed.
        u : array (sd.num_faces) Velocity at each face.
        data: data of the current grid.

        Return
        ------
        P0u : ndarray (3, sd.num_faces) Velocity at each cell.

        """
        # Allow short variable names in backend function
        # pylint: disable=invalid-name

        if sd.dim == 0:
            return np.zeros(3).reshape((3, 1))

        # Get dictionary for discretization matrix storage
        matrix_dictionary = data[pp.DISCRETIZATION_MATRICES][self.keyword]
        proj = matrix_dictionary[self.vector_proj_key]
        # perform the projection
        proj_u = proj.dot(u)

        return proj_u.reshape((3, -1), order="F")

    def _assemble_neumann_common(
        self,
        sd: pp.Grid,
        data: dict,
        M: sps.csr_matrix,
        mass: sps.csr_matrix,
        bc_weight: Optional[float] = None,
    ) -> tuple[sps.csr_matrix, np.ndarray]:
        """Impose Neumann boundary discretization on an already assembled
        system matrix.

        Common implementation for VEM and RT0. The parameter mass should be
        adapted to the discretization method in question

        """

        norm = sps.linalg.norm(mass, np.inf) if bc_weight else 1

        parameter_dictionary = data[pp.PARAMETERS][self.keyword]
        bc = parameter_dictionary["bc"]

        # assign the Neumann boundary conditions
        # For dual discretizations, internal boundaries
        # are handled by assigning Dirichlet conditions. THus, we remove them
        # from the is_neu (where they belong by default) and add them in
        # is_dir.
        is_neu = np.logical_and(bc.is_neu, np.logical_not(bc.is_internal))
        if bc and np.any(is_neu):
            is_neu = np.hstack((is_neu, np.zeros(sd.num_cells, dtype=bool)))
            is_neu = np.where(is_neu)[0]

            # set in an efficient way the essential boundary conditions, by
            # clear the rows and put norm in the diagonal
            for row in is_neu:
                M.data[M.indptr[row] : M.indptr[row + 1]] = 0.0

            d = M.diagonal()
            d[is_neu] = norm
            M.setdiag(d)

        return M, norm

    @staticmethod
    def _velocity_dof(
        sd: pp.Grid, intf: pp.MortarGrid, hat_E_int: sps.csc_matrix
    ) -> sps.csr_matrix:
        # Recover the information for the grid-grid mapping
        faces_h, cells_h, sign_h = sps.find(sd.cell_faces)
        ind_faces_h = np.unique(faces_h, return_index=True)[1]
        cells_h = cells_h[ind_faces_h]
        sign_h = sign_h[ind_faces_h]

        # Velocity degree of freedom matrix
        U = sps.diags(sign_h)

        shape = (sd.num_cells, intf.num_cells)

        hat_E_int = sps.bmat([[U * hat_E_int], [sps.csr_matrix(shape)]])
        return hat_E_int

    def assemble_int_bound_flux(
        self,
        sd: pp.Grid,
        data: dict,
        intf: pp.MortarGrid,
        data_edge: dict,
        cc: np.ndarray,
        matrix: np.ndarray,
        rhs: np.ndarray,
        self_ind: int,
        use_secondary_proj: bool = False,
    ) -> None:
        """Abstract method. Assemble the contribution from an internal
        boundary, manifested as a flux boundary condition.

        The intended use is when the internal boundary is coupled to another
        node in a mixed-dimensional method. Specific usage depends on the
        interface condition between the nodes; this method will typically be
        used to impose flux continuity on a higher-dimensional domain.

        Implementations of this method will use an interplay between the grid on
        the node and the mortar grid on the relevant edge.

        Parameters:
            g (Grid): Grid which the condition should be imposed on.
            data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            data_edge (dictionary): Data dictionary for the edge in the
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
            use_secondary_proj (boolean): If True, the secondary side projection operator is
                used. Needed for periodic boundary conditions.

        """
        msg = """This function is deprecated and will be removed, most likely in the
        second half of 2022.

        To assemble mixed-dimensional elliptic problems, the recommended solution is
        either to use the models, or to use the automatic differentiation framework
        directly.
        """
        warn(msg, DeprecationWarning, stacklevel=2)

        # The matrix must be the VEM discretization matrix.
        if use_secondary_proj:
            proj = intf.mortar_to_secondary_int()
        else:
            proj = intf.mortar_to_primary_int()

        hat_E_int = self._velocity_dof(sd, intf, proj)
        cc[self_ind, 2] += matrix[self_ind, self_ind] * hat_E_int

    def assemble_int_bound_source(
        self,
        sd: pp.Grid,
        data: dict,
        intf: pp.MortarGrid,
        data_edge: dict,
        cc: np.ndarray,
        matrix: np.ndarray,
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
            g (Grid): Grid which the condition should be imposed on.
            data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            data_edge (dictionary): Data dictionary for the edge in the
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
        msg = """This function is deprecated and will be removed, most likely in the
        second half of 2022.

        To assemble mixed-dimensional elliptic problems, the recommended solution is
        either to use the models, or to use the automatic differentiation framework
        directly.
        """
        warn(msg, DeprecationWarning, stacklevel=2)
        proj = intf.secondary_to_mortar_avg()

        A = proj.T
        shape = (sd.num_faces, A.shape[1])
        cc[self_ind, 2] += sps.bmat([[sps.csr_matrix(shape)], [A]])

    def assemble_int_bound_pressure_trace(
        self,
        sd: pp.Grid,
        data: dict,
        intf: pp.MortarGrid,
        data_edge: dict,
        cc: Optional[np.ndarray],
        matrix: np.ndarray,
        rhs: np.ndarray,
        self_ind: int,
        use_secondary_proj: bool = False,
        assemble_matrix=True,
        assemble_rhs=True,
    ) -> None:
        """Abstract method. Assemble the contribution from an internal
        boundary, manifested as a condition on the boundary pressure.

        The intended use is when the internal boundary is coupled to another
        node in a mixed-dimensional method. Specific usage depends on the
        interface condition between the nodes; this method will typically be
        used to impose flux continuity on a higher-dimensional domain.

        Implementations of this method will use an interplay between the grid on
        the node and the mortar grid on the relevant edge.

        Parameters:
            g (Grid): Grid which the condition should be imposed on.
            data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            data_edge (dictionary): Data dictionary for the edge in the
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
            use_secondary_proj (boolean): If True, the secondary side projection operator is
                used. Needed for periodic boundary conditions.

        """
        msg = """This function is deprecated and will be removed, most likely in the
        second half of 2022.

        To assemble mixed-dimensional elliptic problems, the recommended solution is
        either to use the models, or to use the automatic differentiation framework
        directly.
        """
        warn(msg, DeprecationWarning, stacklevel=2)

        if use_secondary_proj:
            proj = intf.mortar_to_secondary_int()
        else:
            proj = intf.mortar_to_primary_int()

        hat_E_int = self._velocity_dof(sd, intf, proj)

        assert cc is not None

        cc[2, self_ind] -= hat_E_int.T * matrix[self_ind, self_ind]
        cc[2, 2] -= hat_E_int.T * matrix[self_ind, self_ind] * hat_E_int

    def assemble_int_bound_pressure_trace_rhs(
        self, sd, data, data_edge, cc, rhs, self_ind, use_secondary_proj=False
    ):
        """Assemble the rhs contribution from an internal
        boundary, manifested as a condition on the boundary pressure.

        For details, see self.assemble_int_bound_pressure_trace()

        Parameters:
            g (Grid): Grid which the condition should be imposed on.
            data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            data_edge (dictionary): Data dictionary for the edge in the
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
            use_secondary_proj (boolean): If True, the secondary side projection operator is
                used. Needed for periodic boundary conditions.

        """
        # Nothing to do here.
        pass

    def assemble_int_bound_pressure_trace_between_interfaces(
        self,
        g: pp.Grid,
        data_grid: dict,
        data_primary_edge,
        data_secondary_edge,
        cc: np.ndarray,
        matrix: np.ndarray,
        rhs: np.ndarray,
    ) -> None:
        """Assemble the contribution from an internal
        boundary, manifested as a condition on the boundary pressure.

        No contribution for this method.

        Parameters:
            g (Grid): Grid which the condition should be imposed on.
            data_grid (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            data_primary_edge (dictionary): Data dictionary for the primary edge in the
                mixed-dimensional grid.
            data_secondary_edge (dictionary): Data dictionary for the secondary edge in the
                mixed-dimensional grid.
            cc (block matrix, 3x3): Block matrix of size 3 x 3, whwere each block represents
                coupling between variables on this interface. Index 0, 1 and 2
                represent the primary grid, the primary and secondary interface,
                respectively.
            matrix (block matrix 3x3): Discretization matrix for the edge and
                the two adjacent nodes.
            rhs (block_array 3x1): Block matrix of size 3 x 1, representing the right hand
                side of this coupling. Index 0, 1 and 2 represent the primary grid,
                the primary and secondary interface, respectively.

        """
        pass

    def assemble_int_bound_pressure_cell(
        self,
        sd: pp.Grid,
        data: dict,
        intf: pp.MortarGrid,
        data_edge: dict,
        cc: np.ndarray,
        matrix: np.ndarray,
        rhs: np.ndarray,
        self_ind: int,
    ) -> None:
        """Abstract method. Assemble the contribution from an internal
        boundary, manifested as a condition on the cell pressure.

        The intended use is when the internal boundary is coupled to another
        node in a mixed-dimensional method. Specific usage depends on the
        interface condition between the nodes; this method will typically be
        used to impose flux continuity on a lower-dimensional domain.

        Implementations of this method will use an interplay between the grid on
        the node and the mortar grid on the relevant edge.

        Parameters:
            sd (Grid): Grid which the condition should be imposed on.
            data (dictionary): Data dictionary for the node in the
                mixed-dimensional grid.
            data_edge (dictionary): Data dictionary for the edge in the
                mixed-dimensional grid.
            grid_swap (boolean): If True, the grid g is identified with the @
                secondary side of the mortar grid in data_adge.
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
        msg = """This function is deprecated and will be removed, most likely in the
        second half of 2022.

        To assemble mixed-dimensional elliptic problems, the recommended solution is
        either to use the models, or to use the automatic differentiation framework
        directly.
        """
        warn(msg, DeprecationWarning, stacklevel=2)

        proj = intf.secondary_to_mortar_avg()

        A = proj.T
        shape = (sd.num_faces, A.shape[1])

        cc[2, self_ind] -= sps.bmat([[sps.csr_matrix(shape)], [A]]).T

    def enforce_neumann_int_bound(
        self,
        sd: pp.Grid,
        intf: pp.MortarGrid,
        data_edge: dict,
        matrix: np.ndarray,
        self_ind: int,
    ) -> None:
        """Enforce Neumann boundary conditions on a given system matrix.

        Methods based on a mixed variational form need this function to
        implement essential boundary conditions.

        The discretization matrix should be modified in place.

        Parameters:
            g (Grid): On which the equation is discretized
            data (dictionary): Of data related to the discretization.
            matrix (scipy.sparse.matrix): Discretization matrix to be modified.
            self_ind (int): Index in local block system of this grid and variable.

        """
        hat_E_int = self._velocity_dof(sd, intf, intf.mortar_to_primary_int())

        dof = np.where(hat_E_int.sum(axis=1).A.astype(bool))[0]
        norm = np.linalg.norm(matrix[self_ind, self_ind].diagonal(), np.inf)

        for row in dof:
            matrix_indptr = matrix[self_ind, self_ind].indptr
            idx = slice(matrix_indptr[row], matrix_indptr[row + 1])
            matrix[self_ind, self_ind].data[idx] = 0.0

            matrix_indptr = matrix[self_ind, 2].indptr
            idx = slice(matrix_indptr[row], matrix_indptr[row + 1])
            matrix[self_ind, 2].data[idx] = 0.0

        d = matrix[self_ind, self_ind].diagonal()
        d[dof] = norm
        matrix[self_ind, self_ind].setdiag(d)

    def extract_flux(
        self, sd: pp.Grid, solution_array: np.ndarray, data: dict
    ) -> np.ndarray:
        """Extract the velocity from a dual virtual element solution.

        Parameters
        ----------
        sd : grid, or a subclass, with geometry fields computed.
        up : array (sd.num_faces+sd.num_cells)
            Solution, stored as [velocity,pressure]
        data: data dictionary associated with the grid.
            Unused, but included for consistency reasons.

        Return
        ------
        u : array (sd.num_faces)
            Velocity at each face.

        """
        # pylint: disable=invalid-name
        return solution_array[: sd.num_faces]

    def extract_pressure(
        self, sd: pp.Grid, solution_array: np.ndarray, data: dict
    ) -> np.ndarray:
        """Extract the pressure from a dual virtual element solution.

        Parameters
        ----------
        sd : grid, or a subclass, with geometry fields computed.
        solution_array : array (sd.num_faces + sd.num_cells)
            Solution, stored as [velocity,pressure]
        data: data dictionary associated with the grid.
            Unused, but included for consistency reasons.

        Return
        ------
        p : array (sd.num_cells)
            Pressure at each cell.

        """
        # pylint: disable=invalid-name
        return solution_array[sd.num_faces :]

    @staticmethod
    def _inv_matrix_1d(K: np.ndarray) -> np.ndarray:
        """Explicit inversion of a matrix 1x1.

        Parameters
        ----------
        K : the matrix to be inverted 1x1

        Return
        ------
        The inverted matrix 1x1
        """
        return np.array([[1.0 / K[0, 0]]])

    @staticmethod
    def _inv_matrix_2d(K: np.ndarray) -> np.ndarray:
        """Explicit inversion of a symmetric matrix 2x2.

        Parameters
        ----------
        K : the matrix to be inverted 2x2

        Return
        ------
        The inverted matrix 2x2
        """
        det = K[0, 0] * K[1, 1] - K[0, 1] * K[0, 1]
        return np.array([[K[1, 1], -K[0, 1]], [-K[0, 1], K[0, 0]]]) / det

    @staticmethod
    def _inv_matrix_3d(K: np.ndarray) -> np.ndarray:
        """Explicit inversion of a symmetric matrix 3x3.

        Parameters
        ----------
        K : the matrix to be inverted 3x3

        Return
        ------
        The inverted matrix 3x3
        """

        det = (
            K[0, 0] * K[1, 1] * K[2, 2]
            - K[0, 0] * K[1, 2] * K[1, 2]
            - K[0, 1] * K[0, 1] * K[2, 2]
            + 2 * K[0, 1] * K[0, 2] * K[1, 2]
            - K[0, 2] * K[0, 2] * K[1, 1]
        )
        return (
            np.array(
                [
                    [
                        K[1, 1] * K[2, 2] - K[1, 2] * K[1, 2],
                        K[0, 2] * K[1, 2] - K[0, 1] * K[2, 2],
                        K[0, 1] * K[1, 2] - K[0, 2] * K[1, 1],
                    ],
                    [
                        K[0, 2] * K[1, 2] - K[0, 1] * K[2, 2],
                        K[0, 0] * K[2, 2] - K[0, 2] * K[0, 2],
                        K[0, 2] * K[1, 0] - K[0, 0] * K[1, 2],
                    ],
                    [
                        K[0, 1] * K[1, 2] - K[0, 2] * K[1, 1],
                        K[0, 1] * K[0, 2] - K[0, 0] * K[1, 2],
                        K[0, 0] * K[1, 1] - K[0, 1] * K[0, 1],
                    ],
                ]
            )
            / det
        )
