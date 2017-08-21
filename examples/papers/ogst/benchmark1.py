import numpy as np
import scipy.sparse as sps

from porepy.viz import exporter
from porepy.fracs import importer

from porepy.params import tensor
from porepy.params.bc import BoundaryCondition
from porepy.params.data import Parameters

from porepy.grids.grid import FaceTag
from porepy.grids import coarsening as co

from porepy.numerics.vem import dual

from porepy.utils.errors import error

#------------------------------------------------------------------------------#

def add_data(gb, domain, kf):
    """
    Define the permeability, apertures, boundary conditions
    """
    gb.add_node_props(['param'])
    tol = 1e-5
    a = 1e-4

    for g, d in gb:
        param = Parameters(g)

        # Permeability
        kxx = np.ones(g.num_cells) * np.power(kf, g.dim < gb.dim_max())
        param.set_tensor("flow", tensor.SecondOrder(g.dim, kxx))

        # Source term
        param.set_source("flow", np.zeros(g.num_cells))

        # Assign apertures
        aperture = np.power(a, gb.dim_max() - g.dim)
        param.set_aperture(np.ones(g.num_cells) * aperture)

        # Boundaries
        bound_faces = g.get_boundary_faces()
        if bound_faces.size != 0:
            bound_face_centers = g.face_centers[:, bound_faces]

            left = bound_face_centers[0, :] < domain['xmin'] + tol
            right = bound_face_centers[0, :] > domain['xmax'] - tol

            labels = np.array(['neu'] * bound_faces.size)
            labels[right] = 'dir'

            bc_val = np.zeros(g.num_faces)
            bc_val[bound_faces[left]] = -aperture \
                                        * g.face_areas[bound_faces[left]]
            bc_val[bound_faces[right]] = 1

            param.set_bc("flow", BoundaryCondition(g, bound_faces, labels))
            param.set_bc_val("flow", bc_val)
        else:
            param.set_bc("flow", BoundaryCondition(
                g, np.empty(0), np.empty(0)))

        d['param'] = param

    # Assign coupling permeability
    gb.add_edge_prop('kn')
    for e, d in gb.edges_props():
        gn = gb.sorted_nodes_of_edge(e)
        aperture = np.power(a, gb.dim_max() - gn[0].dim)
        d['kn'] = np.ones(gn[0].num_cells) * kf / aperture

#------------------------------------------------------------------------------#

def write_network(file_name):
    network = "FID,START_X,START_Y,END_X,END_Y\n"
    network += "0,0,0.5,1,0.5\n"
    network += "1,0.5,0,0.5,1\n"
    network += "2,0.5,0.75,1,0.75\n"
    network += "3,0.75,0.5,0.75,1\n"
    network += "4,0.5,0.625,0.75,0.625\n"
    network += "5,0.625,0.5,0.625,0.75\n"
    with open(file_name, "w") as text_file:
        text_file.write(network)

#------------------------------------------------------------------------------#

def main(kf, known_p, known_u, description, mesh_size):
    mesh_kwargs = {}
    mesh_kwargs['mesh_size'] = {'mode': 'constant',
                                'value': mesh_size, 'bound_value': mesh_size}

    domain = {'xmin': 0, 'xmax': 1, 'ymin': 0, 'ymax': 1}

    file_name = 'network_geiger.csv'
    write_network(file_name)
    gb = importer.from_csv(file_name, mesh_kwargs, domain)
    gb.compute_geometry()
    co.coarsen(gb, 'by_volume')
    gb.assign_node_ordering()

    internal_flag = FaceTag.FRACTURE
    [g.remove_face_tag_if_tag(FaceTag.BOUNDARY, internal_flag) for g, _ in gb]

    # Assign parameters
    add_data(gb, domain, kf)

    # Choose and define the solvers and coupler
    solver = dual.DualVEMMixDim('flow')
    A, b = solver.matrix_rhs(gb)

    up = sps.linalg.spsolve(A, b)
    solver.split(gb, "up", up)

    gb.add_node_props(["discharge", "p", "P0u"])
    for g, d in gb:
        d["discharge"] = solver.discr.extract_u(g, d["up"])
        d["p"] = solver.discr.extract_p(g, d["up"])
        d["P0u"] = solver.discr.project_u(g, d["discharge"], d)

    exporter.export_vtk(gb, 'vem', ["p", "P0u"], folder='vem_' + description,
                        binary=False)

    # Consistency check
    print(np.sum(error.norm_L2(g, d['p']) for g, d in gb))
    print(np.sum(error.norm_L2(g, d['P0u']) for g, d in gb))

#    assert np.isclose(np.sum(error.norm_L2(g, d['p']) for g, d in gb), known_p)
#    assert np.isclose(np.sum(error.norm_L2(g, d['P0u']) for g, d in gb), known_u)

#------------------------------------------------------------------------------#

def vem_blocking():
    kf = 1e-4
    known_p = np.array([35.6446518361, 35.6434707071, 35.6470264787])
    known_u = np.array([1.03180913136, 1.03177583893, 1.03175321947])
    mesh_size = np.array([0.035, 0.0175, 0.00875])

    for i in np.arange(mesh_size.size):
        main(kf, known_p[i], known_u[i], "blocking"+str(i), mesh_size[i])

#------------------------------------------------------------------------------#

def vem_permeable():
    kf = 1e4
    known_p = np.array([19.8453878933, 19.8449307562, 19.8448008744])
    known_u = np.array([1.87878568819, 1.87881987135, 1.8787508862])
    mesh_size = np.array([0.035, 0.0175, 0.00875])

    for i in np.arange(mesh_size.size):
        main(kf, known_p[i], known_u[i], "permeable"+str(i), mesh_size[i])

#------------------------------------------------------------------------------#

vem_blocking()
vem_permeable()
