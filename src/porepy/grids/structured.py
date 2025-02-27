"""Module containing classes for structured grids.

.. rubric:: Acknowledgement

The implementation of structured grids is in practice a translation of the
corresponding functions found in the
`Matlab Reservoir Simulation Toolbox (MRST) <www.sintef.no/projectweb/mrst/>`_
developed by SINTEF ICT.

"""
from __future__ import annotations

from typing import Optional, Union

import numpy as np
import scipy as sp
import scipy.sparse as sps

from porepy.grids.grid import Grid


class TensorGrid(Grid):
    """Representation of a grid formed by a tensor product of line point
    distributions.

    For information on attributes and methods, see the documentation of the
    parent class.

    The resulting grid is 1D or 2D or 3D, depending on the number of
    coordinate lines are provided.

    Parameters:
        x: Node coordinates in x-direction.
        y: ``default=None``

            Node coordinates in y-direction. If None, the created grid will be 1D.
        z: ``default=None``

            Node coordinates in z-direction. If None, the created grid will be 2D.
        name: ``default=None``

            Name for the grid. If None, the grid will be called ``'TensorGrid'``.

    """

    def __init__(
        self,
        x: np.ndarray,
        y: Optional[np.ndarray] = None,
        z: Optional[np.ndarray] = None,
        name: Optional[str] = None,
    ) -> None:

        if name is None:
            name = "TensorGrid"

        self.cart_dims: np.ndarray
        """The resulting dimensions of the of the underlying Cartesian grid."""

        if y is None:
            nodes, face_nodes, cell_faces = self._create_1d_grid(x)
            self.cart_dims = np.array([x.size - 1])
            super().__init__(1, nodes, face_nodes, cell_faces, name)
        elif z is None:
            nodes, face_nodes, cell_faces = self._create_2d_grid(x, y)
            self.cart_dims = np.array([x.size, y.size]) - 1
            super().__init__(2, nodes, face_nodes, cell_faces, name)
        else:
            nodes, face_nodes, cell_faces = self._create_3d_grid(x, y, z)
            self.cart_dims = np.array([x.size, y.size, z.size]) - 1
            super().__init__(3, nodes, face_nodes, cell_faces, name)

    def _create_1d_grid(
        self, nodes_x: np.ndarray
    ) -> tuple[np.ndarray, sps.spmatrix, sps.spmatrix]:
        """Compute the grid topology for 1D grids.

        Parameters:
            nodes_x: Node coordinates in x-direction.

        Returns:
            - The node coordinates in an array of shape ``(3, num_nodes)``.
              y and z coordinates are always zero.
            - A face-to-node map as a sparse matrix.
            - A cell-to-face map as a sparse matrix.

        """

        num_x = nodes_x.size - 1

        num_cells = num_x
        num_nodes = num_x + 1
        num_faces = num_x + 1

        nodes = np.vstack((nodes_x, np.zeros(nodes_x.size), np.zeros(nodes_x.size)))

        # Face nodes
        indptr = np.arange(num_faces + 1)
        face_nodes = np.arange(num_faces)
        data = np.ones(face_nodes.shape, dtype=bool)
        face_nodes = sps.csc_matrix(
            (data, face_nodes, indptr), shape=(num_nodes, num_faces)
        )

        # Cell faces
        face_array = np.arange(num_faces)
        cell_faces = np.vstack((face_array[:-1], face_array[1:])).ravel(order="F")

        num_faces_per_cell = 2
        indptr = np.append(
            np.arange(0, num_faces_per_cell * num_cells, num_faces_per_cell),
            num_faces_per_cell * num_cells,
        )
        data = np.empty(cell_faces.size)
        data[::2] = -1
        data[1::2] = 1

        cell_faces = sps.csc_matrix(
            (data, cell_faces, indptr), shape=(num_faces, num_cells)
        )
        return nodes, face_nodes, cell_faces

    def _create_2d_grid(
        self, nodes_x: np.ndarray, nodes_y: np.ndarray
    ) -> tuple[np.ndarray, sps.spmatrix, sps.spmatrix]:
        """Compute grid topology for 2D grids.

        Parameters:
            nodes_x: Node coordinates in x-direction.
            nodes_y: Node coordinates in y-direction.

        Returns:
            - The node coordinates in an array of shape ``(3, num_nodes)``.
              z coordinates are always zero.
            - A face-to-node map as a sparse matrix.
            - A cell-to-face map as a sparse matrix.

        """
        num_x = nodes_x.size - 1
        num_y = nodes_y.size - 1

        num_cells = num_x * num_y
        num_nodes = (num_x + 1) * (num_y + 1)
        num_faces_x = (num_x + 1) * num_y
        num_faces_y = num_x * (num_y + 1)
        num_faces = num_faces_x + num_faces_y

        num_cells = num_cells
        num_faces = num_faces
        num_nodes = num_nodes

        x_coord, y_coord = sp.meshgrid(nodes_x, nodes_y)

        nodes = np.vstack(
            (x_coord.flatten(), y_coord.flatten(), np.zeros(x_coord.size))
        )

        # Face nodes
        node_array = np.arange(0, num_nodes).reshape(num_y + 1, num_x + 1)
        fn1 = node_array[:-1, ::].ravel(order="C")
        fn2 = node_array[1:, ::].ravel(order="C")
        face_nodes_x = np.vstack((fn1, fn2)).ravel(order="F")

        fn1 = node_array[::, :-1].ravel(order="C")
        fn2 = node_array[::, 1:].ravel(order="C")
        face_nodes_y = np.vstack((fn1, fn2)).ravel(order="F")

        num_nodes_per_face = 2
        indptr = np.append(
            np.arange(0, num_nodes_per_face * num_faces, num_nodes_per_face),
            num_nodes_per_face * num_faces,
        )
        face_nodes = np.hstack((face_nodes_x, face_nodes_y))
        data = np.ones(face_nodes.shape, dtype=bool)
        face_nodes = sps.csc_matrix(
            (data, face_nodes, indptr), shape=(num_nodes, num_faces)
        )

        # Cell faces
        face_x = np.arange(num_faces_x).reshape(num_y, num_x + 1)
        face_y = num_faces_x + np.arange(num_faces_y).reshape(num_y + 1, num_x)

        face_west = face_x[::, :-1].ravel(order="C")
        face_east = face_x[::, 1:].ravel(order="C")
        face_south = face_y[:-1, ::].ravel(order="C")
        face_north = face_y[1:, ::].ravel(order="C")

        cell_faces = np.vstack((face_west, face_east, face_south, face_north)).ravel(
            order="F"
        )

        num_faces_per_cell = 4
        indptr = np.append(
            np.arange(0, num_faces_per_cell * num_cells, num_faces_per_cell),
            num_faces_per_cell * num_cells,
        )
        data = np.vstack(
            (
                -np.ones(face_west.size),
                np.ones(face_east.size),
                -np.ones(face_south.size),
                np.ones(face_north.size),
            )
        ).ravel(order="F")
        cell_faces = sps.csc_matrix(
            (data, cell_faces, indptr), shape=(num_faces, num_cells)
        )
        return nodes, face_nodes, cell_faces

    def _create_3d_grid(
        self, nodes_x: np.ndarray, nodes_y: np.ndarray, nodes_z: np.ndarray
    ) -> tuple[np.ndarray, sps.spmatrix, sps.spmatrix]:
        """Create topology for 3d tensor product grid.

        Parameters:
            nodes_x: Node coordinates in x-direction.
            nodes_y: Node coordinates in y-direction.
            nodes_z: Node coordinates in z-direction.

        Returns:
            - The node coordinates in an array of shape ``(3, num_nodes)``.
            - A face-to-node map as a sparse matrix.
            - A cell-to-face map as a sparse matrix.

        """

        num_x = nodes_x.size - 1
        num_y = nodes_y.size - 1
        num_z = nodes_z.size - 1

        num_cells = num_x * num_y * num_z
        num_nodes = (num_x + 1) * (num_y + 1) * (num_z + 1)
        num_faces_x = (num_x + 1) * num_y * num_z
        num_faces_y = num_x * (num_y + 1) * num_z
        num_faces_z = num_x * num_y * (num_z + 1)
        num_faces = num_faces_x + num_faces_y + num_faces_z

        num_cells = num_cells
        num_faces = num_faces
        num_nodes = num_nodes

        x_coord, y_coord, z_coord = np.meshgrid(nodes_x, nodes_y, nodes_z)
        # This rearrangement turned out to work. Not the first thing I tried.
        x_coord = np.swapaxes(x_coord, 1, 0).ravel(order="F")
        y_coord = np.swapaxes(y_coord, 1, 0).ravel(order="F")
        z_coord = np.swapaxes(z_coord, 1, 0).ravel(order="F")

        nodes = np.vstack((x_coord, y_coord, z_coord))

        # Face nodes
        node_array = np.arange(num_nodes).reshape(
            num_x + 1, num_y + 1, num_z + 1, order="F"
        )

        # Define face-node relations for all x-faces.
        # The code here is a bit different from the corresponding part in
        # 2d, I did learn some tricks in python the past month
        fn1 = node_array[:, :-1, :-1].ravel(order="F")
        fn2 = node_array[:, 1:, :-1].ravel(order="F")
        fn3 = node_array[:, 1:, 1:].ravel(order="F")
        fn4 = node_array[:, :-1, 1:].ravel(order="F")
        face_nodes_x = np.vstack((fn1, fn2, fn3, fn4)).ravel(order="F")

        # Define face-node relations for all y-faces
        fn1 = node_array[:-1:, :, :-1].ravel(order="F")
        fn2 = node_array[:-1, :, 1:].ravel(order="F")
        fn3 = node_array[1:, :, 1:].ravel(order="F")
        fn4 = node_array[1:, :, :-1].ravel(order="F")
        face_nodes_y = np.vstack((fn1, fn2, fn3, fn4)).ravel(order="F")

        # Define face-node relations for all y-faces
        fn1 = node_array[:-1:, :-1, :].ravel(order="F")
        fn2 = node_array[1:, :-1, :].ravel(order="F")
        fn3 = node_array[1:, 1:, :].ravel(order="F")
        fn4 = node_array[:-1, 1:, :].ravel(order="F")
        face_nodes_z = np.vstack((fn1, fn2, fn3, fn4)).ravel(order="F")

        num_nodes_per_face = 4
        indptr = np.append(
            np.arange(0, num_nodes_per_face * num_faces, num_nodes_per_face),
            num_nodes_per_face * num_faces,
        )
        face_nodes = np.hstack((face_nodes_x, face_nodes_y, face_nodes_z))
        data = np.ones(face_nodes.shape, dtype=bool)
        face_nodes = sps.csc_matrix(
            (data, face_nodes, indptr), shape=(num_nodes, num_faces)
        )

        # Cell faces
        face_x = np.arange(num_faces_x).reshape(num_x + 1, num_y, num_z, order="F")
        face_y = num_faces_x + np.arange(num_faces_y).reshape(
            num_x, num_y + 1, num_z, order="F"
        )
        face_z = (
            num_faces_x
            + num_faces_y
            + np.arange(num_faces_z).reshape(num_x, num_y, num_z + 1, order="F")
        )

        face_west = face_x[:-1, :, :].ravel(order="F")
        face_east = face_x[1:, :, :].ravel(order="F")
        face_south = face_y[:, :-1, :].ravel(order="F")
        face_north = face_y[:, 1:, :].ravel(order="F")
        face_top = face_z[:, :, :-1].ravel(order="F")
        face_bottom = face_z[:, :, 1:].ravel(order="F")

        cell_faces = np.vstack(
            (face_west, face_east, face_south, face_north, face_top, face_bottom)
        ).ravel(order="F")

        num_faces_per_cell = 6
        indptr = np.append(
            np.arange(0, num_faces_per_cell * num_cells, num_faces_per_cell),
            num_faces_per_cell * num_cells,
        )
        data = np.vstack(
            (
                -np.ones(num_cells),
                np.ones(num_cells),
                -np.ones(num_cells),
                np.ones(num_cells),
                -np.ones(num_cells),
                np.ones(num_cells),
            )
        ).ravel(order="F")
        cell_faces = sps.csc_matrix(
            (data, cell_faces, indptr), shape=(num_faces, num_cells)
        )
        return nodes, face_nodes, cell_faces


class CartGrid(TensorGrid):
    """Representation of a 2D or 3D Cartesian grid.

    The name ``'CartGrid'`` is assigned to each instance.

    Parameters:
        nx: Number of cells in each direction (x, y or z).

            Should be 1d, 2d or 3d.
            1d grids can also be specified by a scalar.
        physdims: ``default=None``

            Physical dimensions in each direction.

            Can be given as an array with up to 3 entries (for each dimension).

            Can also be given as a dictionary with keys

                - ``'xmin'``, ``'xmax'``,
                - ``'ymin'``, ``'ymax'`` (optional if 1D),
                - ``'zmin'``, ``'zmax'`` (optional if 1D or 2D).

            If None, the number of cells in each direction is used, i.e. the cells
            will be of unit size.

    """

    def __init__(
        self,
        nx: np.ndarray,
        physdims: Optional[Union[np.ndarray, dict[str, float]]] = None,
    ) -> None:

        dims = np.asarray(nx).shape
        xmin, ymin, zmin = 0.0, 0.0, 0.0

        if physdims is None:
            physdims = np.asarray(nx)
        elif isinstance(physdims, dict):
            xmin = physdims["xmin"]
            ymin = physdims.get("ymin", 0.0)
            zmin = physdims.get("zmin", 0.0)

            physdims = np.asarray(
                [
                    physdims["xmax"] - xmin,
                    physdims.get("ymax", 0) - ymin,
                    physdims.get("zmax", 0) - zmin,
                ]
            )

        name = "CartGrid"

        # Create point distribution, and then leave construction to
        # TensorGrid constructor
        if len(dims) == 0:
            nodes_x = xmin + np.linspace(0, physdims, nx + 1)
            super().__init__(nodes_x.T, name=name)
        elif dims[0] == 1:
            nodes_x = np.linspace(0, physdims, nx[0] + 1).ravel()
            super().__init__(nodes_x, name=name)
        elif dims[0] == 2:
            nodes_x = xmin + np.linspace(0, physdims[0], nx[0] + 1)
            nodes_y = ymin + np.linspace(0, physdims[1], nx[1] + 1)
            super().__init__(nodes_x, nodes_y, name=name)
        elif dims[0] == 3:
            nodes_x = xmin + np.linspace(0, physdims[0], nx[0] + 1)
            nodes_y = ymin + np.linspace(0, physdims[1], nx[1] + 1)
            nodes_z = zmin + np.linspace(0, physdims[2], nx[2] + 1)
            super().__init__(nodes_x, nodes_y, nodes_z, name=name)
        else:
            raise ValueError(
                "Cartesian grid only implemented for up to three \
            dimensions"
            )

        self.global_point_ind = np.arange(self.num_nodes)
