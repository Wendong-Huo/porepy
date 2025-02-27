"""Tests of grid_operator classes, currently covering
    SubdomainProjections
    MortarProjections
    Geometry
    Trace
    Divergence
    BoundaryCondition
    ParameterVector
    ParameterMatrix

Tests of the base Discretization class are also placed here.
"""
from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sps

import porepy as pp


def set_parameters(
    dim: int,
    subdomains: list[pp.Grid],
    key: str,
    mdg: pp.MixedDimensionalGrid,
    f_or_c="faces",
):
    """Set two parameters in the data dictionary.

    Args:
        dim: Dimension of the two parameters. 1 corresponds to face-wise scalars, higher
            integers to vectors.
        subdomains: Subdomains for which data is assigned. Should be in mdg.subdomains().
        key: Parameter keyword.
        mdg: Mixed-dimensional grid.

    Returns:
        known_values (np.ndarray): The assigned values concatenated in the order defined by
            subdomains.
        face_indices (list): Each element contains the indices for extracting the known_values
            of the corresponding subdomain in the subdomains list.

    """
    np.random.seed(42)
    # Start of all faces. If vector problem, all faces have dim numbers
    start_inds = dim * np.cumsum(
        np.hstack((0, np.array([getattr(sd, "num_" + f_or_c) for sd in subdomains])))
    )

    # Build values of known values (to be filled during assignment of bcs)
    known_values = np.zeros(
        sum([getattr(sd, "num_" + f_or_c) for sd in subdomains]) * dim
    )
    indices = []
    # Loop over grids, assign values, keep track of assigned values
    for sd in subdomains:
        data = mdg.subdomain_data(sd)
        grid_ind = _list_ind_of_grid(subdomains, sd)
        # Repeat values along the vector dimension to enable comparison with
        # parameters expanded from face-wise scalar to face-wise vector using
        # the geometry operator.
        values = np.random.rand(getattr(sd, "num_" + f_or_c))
        if sd.dim > 0:
            # The if is just to avoid problems with kron when values is empty.
            values = np.kron(values, np.ones(dim))

        pp.initialize_data(
            sd,
            data,
            key,
            {
                "bc_values": values,
                "parameter_key": values,
            },
        )

        # Put face values in the right place in the vector of knowns
        inds_loc = np.arange(start_inds[grid_ind], start_inds[grid_ind + 1])
        known_values[inds_loc] = values
        indices.append(inds_loc)

    return known_values, indices


def geometry_information(
    mdg: pp.MixedDimensionalGrid, dim: int
) -> tuple[int, int, int]:
    """Geometry information used in multiple test methods.

    Args:
        mdg: Mixed-dimensional grid.
        dim: Dimension. Each of the return values is multiplied by dim.

    Returns:
        n_cells (int): Number of subdomain cells.
        n_faces (int): Number of subdomain faces.
        n_mortar_cells (int): Number of interface cells.
    """
    n_cells = sum([sd.num_cells for sd in mdg.subdomains()]) * dim
    n_faces = sum([sd.num_faces for sd in mdg.subdomains()]) * dim
    n_mortar_cells = sum([intf.num_cells for intf in mdg.interfaces()]) * dim
    return n_cells, n_faces, n_mortar_cells


@pytest.fixture
def mdg():
    """Provide a mixed-dimensional grid for the tests."""
    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    md_grid = pp.meshing.cart_grid(fracs, np.array([2, 2]))
    return md_grid


@pytest.mark.parametrize("scalar", [True, False])
def test_subdomain_projections(mdg, scalar):
    """Test of subdomain projections. Both face and cell restriction and prolongation.

    Test three specific cases:
        1. Projections generated by passing a md-grid and a list of grids are identical
        2. All projections for all grids (individually) in a simple md-grid.
        3. Combined projections for list of grids.
    """
    proj_dim = 1 if scalar else mdg.dim_max()
    n_cells, n_faces, _ = geometry_information(mdg, proj_dim)

    subdomains = mdg.subdomains()
    proj = pp.ad.SubdomainProjections(subdomains=subdomains, dim=proj_dim)

    cell_start = np.cumsum(
        np.hstack((0, np.array([sd.num_cells for sd in subdomains])))
    )
    face_start = np.cumsum(
        np.hstack((0, np.array([sd.num_faces for sd in subdomains])))
    )

    # Helper method to get indices for sparse matrices
    def _mat_inds(nc, nf, grid_ind, dim, cell_start, face_start):
        cell_inds = np.arange(cell_start[grid_ind], cell_start[grid_ind + 1])
        face_inds = np.arange(face_start[grid_ind], face_start[grid_ind + 1])

        data_cell = np.ones(nc * dim)
        row_cell = np.arange(nc * dim)
        data_face = np.ones(nf * dim)
        row_face = np.arange(nf * dim)
        col_cell = pp.fvutils.expand_indices_nd(cell_inds, dim)
        col_face = pp.fvutils.expand_indices_nd(face_inds, dim)
        return row_cell, col_cell, data_cell, row_face, col_face, data_face

    # Test projection of one fracture at a time for the full set of grids
    for sd in subdomains:

        ind = _list_ind_of_grid(subdomains, sd)

        nc, nf = sd.num_cells, sd.num_faces

        num_rows_cell = nc * proj_dim
        num_rows_face = nf * proj_dim

        row_cell, col_cell, data_cell, row_face, col_face, data_face = _mat_inds(
            nc, nf, ind, proj_dim, cell_start, face_start
        )

        known_cell_proj = sps.coo_matrix(
            (data_cell, (row_cell, col_cell)), shape=(num_rows_cell, n_cells)
        ).tocsr()
        known_face_proj = sps.coo_matrix(
            (data_face, (row_face, col_face)), shape=(num_rows_face, n_faces)
        ).tocsr()

        assert _compare_matrices(proj.cell_restriction([sd]), known_cell_proj)
        assert _compare_matrices(proj.cell_prolongation([sd]), known_cell_proj.T)
        assert _compare_matrices(proj.face_restriction([sd]), known_face_proj)
        assert _compare_matrices(proj.face_prolongation([sd]), known_face_proj.T)

    # Project between the full grid and both 1d grids (to combine two grids)
    g1, g2 = mdg.subdomains(dim=1)
    rc1, cc1, dc1, rf1, cf1, df1 = _mat_inds(
        g1.num_cells,
        g1.num_faces,
        _list_ind_of_grid(subdomains, g1),
        proj_dim,
        cell_start,
        face_start,
    )
    rc2, cc2, dc2, rf2, cf2, df2 = _mat_inds(
        g2.num_cells,
        g2.num_faces,
        _list_ind_of_grid(subdomains, g2),
        proj_dim,
        cell_start,
        face_start,
    )

    # Adjust the indices of the second grid, we will stack the matrices.
    rc2 += rc1.size
    rf2 += rf1.size
    num_rows_cell = (g1.num_cells + g2.num_cells) * proj_dim
    num_rows_face = (g1.num_faces + g2.num_faces) * proj_dim

    known_cell_proj = sps.coo_matrix(
        (np.hstack((dc1, dc2)), (np.hstack((rc1, rc2)), np.hstack((cc1, cc2)))),
        shape=(num_rows_cell, n_cells),
    ).tocsr()
    known_face_proj = sps.coo_matrix(
        (np.hstack((df1, df2)), (np.hstack((rf1, rf2)), np.hstack((cf1, cf2)))),
        shape=(num_rows_face, n_faces),
    ).tocsr()

    assert _compare_matrices(proj.cell_restriction([g1, g2]), known_cell_proj)
    assert _compare_matrices(proj.cell_prolongation([g1, g2]), known_cell_proj.T)
    assert _compare_matrices(proj.face_restriction([g1, g2]), known_face_proj)
    assert _compare_matrices(proj.face_prolongation([g1, g2]), known_face_proj.T)


@pytest.mark.parametrize("scalar", [True, False])
def test_mortar_projections(mdg, scalar):
    # Test of mortar projections between mortar grids and standard subdomain grids.

    proj_dim = 1 if scalar else mdg.dim_max()
    n_cells, n_faces, n_mortar_cells = geometry_information(mdg, proj_dim)

    g0 = mdg.subdomains(dim=2)[0]
    g1, g2 = mdg.subdomains(dim=1)
    g3 = mdg.subdomains(dim=0)[0]

    intf01 = mdg.subdomain_pair_to_interface((g0, g1))
    intf02 = mdg.subdomain_pair_to_interface((g0, g2))

    intf13 = mdg.subdomain_pair_to_interface((g1, g3))
    intf23 = mdg.subdomain_pair_to_interface((g2, g3))

    ########
    # First test projection between all grids and all interfaces
    subdomains = [g0, g1, g2, g3]
    interfaces = [intf01, intf02, intf13, intf23]

    proj = pp.ad.MortarProjections(
        subdomains=subdomains, interfaces=interfaces, mdg=mdg, dim=proj_dim
    )

    cell_start = proj_dim * np.cumsum(
        np.hstack((0, np.array([g.num_cells for g in subdomains])))
    )
    face_start = proj_dim * np.cumsum(
        np.hstack((0, np.array([g.num_faces for g in subdomains])))
    )

    f0 = np.hstack(
        (
            sps.find(intf01.mortar_to_primary_int(nd=proj_dim))[0],
            sps.find(intf02.mortar_to_primary_int(nd=proj_dim))[0],
        )
    )
    f1 = sps.find(intf13.mortar_to_primary_int(nd=proj_dim))[0]
    f2 = sps.find(intf23.mortar_to_primary_int(nd=proj_dim))[0]

    c1 = sps.find(intf01.mortar_to_secondary_int(nd=proj_dim))[0]
    c2 = sps.find(intf02.mortar_to_secondary_int(nd=proj_dim))[0]
    c3 = np.hstack(
        (
            sps.find(intf13.mortar_to_secondary_int(nd=proj_dim))[0],
            sps.find(intf23.mortar_to_secondary_int(nd=proj_dim))[0],
        )
    )

    rows_higher = np.hstack((f0, f1 + face_start[1], f2 + face_start[2]))
    cols_higher = np.arange(n_mortar_cells)
    data = np.ones(n_mortar_cells)

    proj_known_higher = sps.coo_matrix(
        (data, (rows_higher, cols_higher)), shape=(n_faces, n_mortar_cells)
    ).tocsr()

    assert _compare_matrices(proj_known_higher, proj.mortar_to_primary_int)
    assert _compare_matrices(proj_known_higher, proj.mortar_to_primary_avg)
    assert _compare_matrices(proj_known_higher.T, proj.primary_to_mortar_int)
    assert _compare_matrices(proj_known_higher.T, proj.primary_to_mortar_avg)

    rows_lower = np.hstack((c1 + cell_start[1], c2 + cell_start[2], c3 + cell_start[3]))
    cols_lower = np.arange(n_mortar_cells)
    data = np.ones(n_mortar_cells)

    proj_known_lower = sps.coo_matrix(
        (data, (rows_lower, cols_lower)), shape=(n_cells, n_mortar_cells)
    ).tocsr()
    assert _compare_matrices(proj_known_lower, proj.mortar_to_secondary_int)

    # Also test block matrices for the sign of mortar projections.
    # This is a diagonal matrix with first -1, then 1.
    # If this test fails, something is fundamentally wrong.
    vals = np.array([])
    for intf in interfaces:
        sz = int(np.round(intf.num_cells / 2) * proj_dim)
        vals = np.hstack((vals, -np.ones(sz), np.ones(sz)))

    known_sgn_mat = sps.dia_matrix((vals, 0), shape=(n_mortar_cells, n_mortar_cells))
    assert _compare_matrices(known_sgn_mat, proj.sign_of_mortar_sides)


@pytest.mark.parametrize("scalar", [True, False])
def test_boundary_grid_projection(mdg: pp.MixedDimensionalGrid, scalar: bool):
    """Aspects to test:
    1) That we can create a boundary projection operator with the correct size and items.
    2) Specifically that the top-dimensional grid and one of the fracture grids
       contribute to the boundary projection operator, while the third has a projection
       matrix with zero rows.
    """
    proj_dim = 1 if scalar else mdg.dim_max()
    _, num_faces, _ = geometry_information(mdg, proj_dim)
    num_cells = sum([bg.num_cells for bg in mdg.boundaries()]) * proj_dim

    g_0 = mdg.subdomains(dim=2)[0]
    g_1, g_2 = mdg.subdomains(dim=1)
    # Compute geometry for the mixed-dimensional grid. This is needed for
    # boundary projection operator.
    mdg.compute_geometry()
    projection = pp.ad.grid_operators.BoundaryProjection(
        mdg, mdg.subdomains(), proj_dim
    )
    # Check sizes.
    assert projection.subdomain_to_boundary().shape == (num_cells, num_faces)
    assert projection.boundary_to_subdomain().shape == (num_faces, num_cells)

    # Check that the projection matrix for the top-dimensional grid is non-zero.
    # The matrix has eight boundary faces.
    ind0 = 0
    ind1 = g_0.num_faces * proj_dim
    assert np.sum(projection.subdomain_to_boundary()[:, ind0:ind1]) == 8 * proj_dim
    # Check that the projection matrix for the first fracture is non-zero. Since the
    # fracture touches the boundary on two sides, we expect two non-zero rows.
    ind0 = ind1
    ind1 += g_1.num_faces * proj_dim
    assert np.sum(projection.subdomain_to_boundary()[:, ind0:ind1]) == 2 * proj_dim
    # Check that the projection matrix for the second fracture is non-zero.
    ind0 = ind1
    ind1 += g_2.num_faces * proj_dim
    assert np.sum(projection.subdomain_to_boundary()[:, ind0:ind1]) == 2 * proj_dim
    # The projection matrix for the intersection should be zero.
    ind0 = ind1
    assert np.sum(projection.subdomain_to_boundary()[:, ind0:]) == 0

    # Make second projection on subset of grids.
    subdomains = [g_0, g_1]
    projection = pp.ad.grid_operators.BoundaryProjection(mdg, subdomains, proj_dim)
    num_faces = proj_dim * (g_0.num_faces + g_1.num_faces)
    num_cells = proj_dim * sum(
        [mdg.subdomain_to_boundary_grid(sd).num_cells for sd in subdomains]
    )
    # Check sizes.
    assert projection.subdomain_to_boundary().shape == (num_cells, num_faces)
    assert projection.boundary_to_subdomain().shape == (num_faces, num_cells)

    # Check that the projection matrix for the top-dimensional grid is non-zero.
    # Same sizes as above.
    ind0 = 0
    ind1 = g_0.num_faces * proj_dim
    assert np.sum(projection.subdomain_to_boundary()[:, ind0:ind1]) == 8 * proj_dim
    ind0 = ind1
    ind1 += g_1.num_faces * proj_dim
    assert np.sum(projection.subdomain_to_boundary()[:, ind0:ind1]) == 2 * proj_dim


@pytest.mark.parametrize("scalar", [True, False])
def test_boundary_condition(mdg: pp.MixedDimensionalGrid, scalar: bool):
    """Test of boundary condition representation.

    Args:
        mdg: Mixed-dimensional grid.
        scalar:

    Returns:

    """
    subdomains = mdg.subdomains()
    dim = 1 if scalar else mdg.dim_max()
    key = "foo"

    known_values, _ = set_parameters(dim, subdomains, key, mdg)

    # Ad representation of the boundary conditions.
    op = pp.ad.BoundaryCondition(key, subdomains)

    # Parse.
    val = op.parse(mdg)

    assert np.allclose(val, known_values)


@pytest.mark.parametrize("scalar", [True, False])
def test_parameter(mdg: pp.MixedDimensionalGrid, scalar: bool):
    """Test of boundary condition representation."""
    subdomains = mdg.subdomains()
    dim = 1 if scalar else mdg.dim_max()
    key = "foo"

    known_values, _ = set_parameters(dim, subdomains, key, mdg)

    # Ad representation of the boundary conditions.
    if scalar:
        op = pp.ad.ParameterArray(key, "parameter_key", subdomains)
    else:
        op = pp.ad.ParameterMatrix(key, "parameter_key", subdomains)
        known_values = sps.diags(known_values)

    # Parse.
    val = op.parse(mdg)
    if scalar:
        assert np.allclose(val, known_values)
    else:
        assert _compare_matrices(val, known_values)


# Geometry based operators
def test_trace(mdg: pp.MixedDimensionalGrid):
    """Test Trace operator.

    Args:
        mdg: Mixed-dimensional grid.

    This test is not ideal. It follows the implementation of Trace relatively closely,
    but nevertheless provides some coverage, especially if Trace is carelessly changed.
    The test constructs the expected md trace and inv_trace matrices and compares them
    to the ones of Trace. Also checks that an error is raised if a non-scalar trace is
    constructed (not implemented).
    """
    # The operator should work on any subset of mdg.subdomains.
    subdomains = mdg.subdomains(dim=1)

    # Construct expected matrices
    traces, inv_traces = list(), list()
    # No check on this function here.
    # TODO: A separate unit test might be appropriate.
    cell_projections, face_projections = pp.ad.grid_operators._subgrid_projections(
        subdomains, dim=1
    )
    for sd in subdomains:
        local_block = np.abs(sd.cell_faces.tocsr())
        traces.append(local_block * cell_projections[sd].T)
        inv_traces.append(local_block.T * face_projections[sd].T)

    # Compare to operator class
    op = pp.ad.Trace(subdomains)
    _compare_matrices(op.trace, sps.bmat([[m] for m in traces]))
    _compare_matrices(op.inv_trace, sps.bmat([[m] for m in inv_traces]))

    # As of the writing of this test, Trace is not implemented for vector values.
    # If it is ever extended, the test should be extended accordingly (e.g. parametrized with
    # dim=[1, 2]).
    with pytest.raises(NotImplementedError):
        pp.ad.Trace(subdomains, dim=2)


@pytest.mark.parametrize(
    "sd_inds",
    [
        slice(0, 2),
        slice(1, 3),
    ],
)
@pytest.mark.parametrize("nd", [3, 2])
def test_geometry(mdg: pp.MixedDimensionalGrid, sd_inds: slice, nd: int):
    """Test Geometry.

    Args:
        mdg: Mixed-dimensional grid.
        sd_inds: Which of the mdg's subdomains to use.
        nd: Ambient dimension.

    Checks that
        1) the following attributes are as expected:
            cell_volumes
            face_areas
            num_cells
            num_faces
        2) the action of face_areas and scalar_to_nd_face on a parameter array are as expected.
            This might belong in an integration test. The cell equivalents are constructed by
            the same functions, so are not tested here (could be added).
        3)
    """
    # This test is not ideal. It follows the implementation of Trace relatively closely,
    # but nevertheless provides some coverage.

    # The operator should work on any subset of mdg.subdomains.
    subdomains = mdg.subdomains()[sd_inds]
    cell_volumes, face_areas = list(), list()

    for sd in subdomains:
        cell_volumes.append(sd.cell_volumes)
        face_areas.append(sd.face_areas)
    op = pp.ad.Geometry(subdomains, nd)
    _compare_matrices(op.cell_volumes, sps.diags(np.hstack(cell_volumes)))
    _compare_matrices(op.face_areas, sps.diags(np.hstack(face_areas)))
    assert op.num_cells == sum(sd.num_cells for sd in subdomains)
    assert op.num_faces == sum(sd.num_faces for sd in subdomains)

    # Check the action of the Geometry on other (face-wise) objects.
    # 1: Face area weighting
    # 2: Expansion from face-wise scalar to nd. I.e., [a, b, c, ...] becomes
    # [a, a, a, b, b, b, c, c, c, ...] in the case nd=3.
    key = "foo"
    known_vectors, vector_inds = set_parameters(nd, subdomains, key, mdg)

    known_scalars, scalar_inds = set_parameters(1, subdomains, key, mdg)
    array = pp.ad.ParameterArray(key, "parameter_key", subdomains)
    # Expand to vector
    for sd, inds in zip(subdomains, scalar_inds):
        known_scalars[inds] *= sd.face_areas

    scalar_vals = op.face_areas.parse(mdg) * array.parse(mdg)
    assert np.all(np.isclose(scalar_vals, known_scalars))
    # Vector assignment overwrites from scalar to vector parameter and must therefore be done
    # after scalar check.
    vector_vals = op.scalar_to_nd_face.parse(mdg) * array.parse(mdg)

    assert np.all(np.isclose(vector_vals, known_vectors))
    # Trigger sanity check on dimension of subdomains exceeding ambient dimension
    with pytest.raises(AssertionError):
        pp.ad.Geometry(subdomains, nd=subdomains[0].dim - 1)

    known_cell_vectors, cell_inds = set_parameters(nd, subdomains, key, mdg, "cells")
    cell_array = pp.ad.ParameterArray(key, "parameter_key", subdomains)

    # Test basis vectors
    for i in range(nd):
        e = op.e_i(i)
        # Inner product with array
        v = e.transpose().parse(mdg) * cell_array.parse(mdg)
        assert np.all(np.isclose(v, known_cell_vectors[i::nd]))
        # Test that the vectors are orthogonal
        for j in range(nd):
            # Inner product with e_j
            d_ij = e.transpose().parse(mdg) * op.e_i(j).parse(mdg)
            if i == j:
                identity = np.eye(d_ij.shape[0])
                assert np.all(np.isclose(d_ij.todense(), identity))
            else:
                assert np.all(np.isclose(d_ij.todense(), 0))

    # Test that scalar to nd equals sum of basis vectors
    basis_sum = sum(op.e_i(i).parse(mdg) for i in range(nd))
    assert np.all(
        np.isclose(basis_sum.todense(), op.scalar_to_nd_cell.parse(mdg).todense())
    )
    # The former will probably be deprecated.


@pytest.mark.parametrize("dim", [1, 4])
def test_divergence(mdg: pp.MixedDimensionalGrid, dim: int):
    """Test Divergence.

    Args:
        mdg: Mixed-dimensional grid.
        dim: Dimension of vector field to which Divergence is applied.

    This test is not ideal. It follows the implementation of Divergence relatively closely,
    but nevertheless provides some coverage. Frankly, there is not much more to do than
    comparing against the expected matrices, unless one wants to add more integration-type
    tests e.g. evaluating combinations with other ad entities.
    """
    # The operator should work on any subset of mdg.subdomains.
    subdomains = mdg.subdomains(dim=2) + mdg.subdomains(dim=0)

    # Construct expected matrix
    divergences = list()
    for sd in subdomains:
        # Kron does no harm if dim=1
        local_block = sps.kron(sd.cell_faces.tocsr().T, sps.eye(dim))
        divergences.append(local_block)

    # Compare to operators parsed value
    op = pp.ad.Divergence(subdomains)
    val = op.parse(mdg)
    _compare_matrices(val, sps.block_diag(divergences))


def test_ad_discretization_class():
    # Test of the mother class of all discretizations (pp.ad.Discretization)

    fracs = [np.array([[0, 2], [1, 1]]), np.array([[1, 1], [0, 2]])]
    mdg = pp.meshing.cart_grid(fracs, np.array([2, 2]))

    subdomains = [g for g in mdg.subdomains()]
    sub_list = subdomains[:2]

    # Make two Mock discretizations, with different keywords
    key = "foo"
    sub_key = "bar"
    discr = _MockDiscretization(key)
    sub_discr = _MockDiscretization(sub_key)

    # Ad wrappers
    # This mimics the old init of Discretization, before it was decided to
    # make that class semi-ABC. Still checks the wrap method
    discr_ad = pp.ad.Discretization()
    discr_ad.subdomains = subdomains
    discr_ad._discretization = discr
    pp.ad._ad_utils.wrap_discretization(discr_ad, discr, subdomains)
    sub_discr_ad = pp.ad.Discretization()
    sub_discr_ad.subdomains = sub_list
    sub_discr_ad._discretization = sub_discr
    pp.ad._ad_utils.wrap_discretization(sub_discr_ad, sub_discr, sub_list)

    # values
    known_val = np.random.rand(len(subdomains))
    known_sub_val = np.random.rand(len(sub_list))

    # Assign a value to the discretization matrix, with the right key
    for vi, sd in enumerate(subdomains):
        data = mdg.subdomain_data(sd)
        data[pp.DISCRETIZATION_MATRICES] = {key: {"foobar": known_val[vi]}}

    # Same with submatrix
    for vi, sd in enumerate(sub_list):
        data = mdg.subdomain_data(sd)
        data[pp.DISCRETIZATION_MATRICES].update(
            {sub_key: {"foobar": known_sub_val[vi]}}
        )

    # Compare values under parsing. Note we need to pick out the diagonal, due to the
    # way parsing makes block matrices.
    assert np.allclose(known_val, discr_ad.foobar.parse(mdg).diagonal())
    assert np.allclose(known_sub_val, sub_discr_ad.foobar.parse(mdg).diagonal())


## Below are helpers for tests of the Ad wrappers.


def _compare_matrices(m1, m2):
    if isinstance(m1, pp.ad.Matrix):
        m1 = m1._mat
    if isinstance(m2, pp.ad.Matrix):
        m2 = m2._mat
    if m1.shape != m2.shape:
        return False
    d = m1 - m2
    if d.data.size > 0:
        if np.max(np.abs(d.data)) > 1e-10:
            return False
    return True


def _list_ind_of_grid(subdomains, g):
    for i, gl in enumerate(subdomains):
        if g == gl:
            return i

    raise ValueError("grid is not in list")


class _MockDiscretization:
    def __init__(self, key):
        self.foobar_matrix_key = "foobar"
        self.not_matrix_keys = "failed"

        self.keyword = key
