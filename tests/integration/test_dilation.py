"""
Various integration tests for contact mechanics.
"""
import tests.common.contact_mechanics_examples
import unittest

import numpy as np

import porepy as pp


class TestDilation(unittest.TestCase):
    def _solve(self, setup):
        if hasattr(setup, "time_manager"):
            pp.run_time_dependent_model(setup, {"convergence_tol": 1e-10})
        else:
            pp.run_stationary_model(setup, {"convergence_tol": 1e-10})
        mdg = setup.mdg

        nd = mdg.dim_max()
        sd_2 = mdg.subdomains(dim=nd)[0]
        sd_1 = mdg.subdomains(dim=nd - 1)[0]
        intf = mdg.subdomain_pair_to_interface((sd_1, sd_2))
        intf_data = mdg.interface_data(intf)

        sd_1_data = mdg.subdomain_data(sd_1)

        u_mortar = intf_data[pp.STATE][setup.mortar_displacement_variable]
        contact_force = sd_1_data[pp.STATE][setup.contact_traction_variable]

        displacement_jump_global_coord = (
            intf.mortar_to_secondary_avg(nd=nd)
            * intf.sign_of_mortar_sides(nd=nd)
            * u_mortar
        )
        projection = sd_1_data["tangential_normal_projection"]

        project_to_local = projection.project_tangential_normal(int(intf.num_cells / 2))
        u_mortar_local = project_to_local * displacement_jump_global_coord
        u_mortar_local_decomposed = u_mortar_local.reshape((2, -1), order="F")

        contact_force = contact_force.reshape((2, -1), order="F")

        return u_mortar_local_decomposed, contact_force

    def test_zero_boundary_constant_gap(self):
        """
        Test contact mechanics with a nonzero constant gap.
        """
        setup = SetupContactMechanics(
            ux_south=0.0, uy_south=0.0, ux_north=0, uy_north=0
        )
        setup.initial_gap = 1e-4
        u_mortar, contact_force = self._solve(setup)

        # All cells should be displaced in the normal direction
        self.assertTrue(np.all(np.isclose(u_mortar[1], setup.initial_gap)))

        # The contact force in normal direction should be negative for
        # "mechanically closed" fractures, i.e. u_n = g.
        self.assertTrue(np.all(contact_force[1] < setup.zero_tol))

    def test_displace_south_constant_gap(self):
        """
        Test contact mechanics with a nonzero constant gap.
        """
        setup = SetupContactMechanics(
            ux_south=0.0, uy_south=0.001, ux_north=0, uy_north=0
        )
        setup.initial_gap = 1e-4 * np.random.rand(2)
        u_mortar, contact_force = self._solve(setup)

        # Normal displacement should equal initial gap
        self.assertTrue(np.all(np.isclose(u_mortar[1], setup.initial_gap)))

        # The contact force in normal direction should be negative.
        self.assertTrue(np.all(contact_force[1] < setup.zero_tol))

    def test_displace_south_xy_constant_gap(self):
        """Displace also in x direction to test same as above for sliding."""
        setup = SetupContactMechanics(
            ux_south=0.01, uy_south=0.001, ux_north=0, uy_north=0
        )
        setup.initial_gap = 1e-4 * np.random.rand(2)
        u_mortar, contact_force = self._solve(setup)

        # Normal displacement should equal initial gap
        self.assertTrue(np.all(np.isclose(u_mortar[1], setup.initial_gap)))

        # The contact force in normal direction should be negative for closed fractures.
        self.assertTrue(np.all(contact_force[1] < setup.zero_tol))

    def test_displace_south_x_nonconstant_gap(self):
        """Displace also in x direction to test same as above for sliding."""
        setup = SetupContactMechanics(
            ux_south=0.1, uy_south=0.0, ux_north=0, uy_north=0
        )
        setup.dilation_angle = np.pi / 3
        u_mortar, contact_force = self._solve(setup)

        # We expect dilation
        self.assertTrue(np.all(u_mortar[1] > setup.zero_tol))
        # Check that the ratio between displacement jumps equals the dilation angle
        abs_u = np.absolute(u_mortar)
        self.assertTrue(
            np.all(np.isclose(abs_u[1] / abs_u[0], np.tan(setup.dilation_angle)))
        )
        # The contact force in normal direction should be negative for closed fractures.
        self.assertTrue(np.all(contact_force[1] < setup.zero_tol))

    def test_pull_south_closed(self):
        """Pull downwards and displace in x direction. Due to large dilation angle,
        the fracture remains closed."""
        setup = SetupContactMechanics(
            ux_south=0.1, uy_south=-0.1, ux_north=0, uy_north=0
        )
        setup.dilation_angle = np.pi / 3
        setup.fracture_endpoints = np.array([0.0, 1.0])
        u_mortar, contact_force = self._solve(setup)

        # We expect dilation
        self.assertTrue(np.all(u_mortar[1] > 1e-7))
        # Check that the ratio between displacement jumps equals the dilation angle
        abs_u = np.absolute(u_mortar)
        self.assertTrue(
            np.all(np.isclose(abs_u[1] / abs_u[0], np.tan(setup.dilation_angle)))
        )
        # The contact force in normal direction should be negative for closed fractures.
        self.assertTrue(np.all(contact_force[1] < setup.zero_tol))

    def test_pull_south_open(self):
        """Pull downwards and displace in x direction. Due to smaller dilation angle
        than above, fracture is open closed."""
        setup = SetupContactMechanics(
            ux_south=0.1, uy_south=-0.1, ux_north=0, uy_north=0
        )
        setup.dilation_angle = np.pi / 6
        setup.fracture_endpoints = np.array([0.0, 1.0])
        u_mortar, contact_force = self._solve(setup)

        # Check that the ratio between displacement jumps equals the dilation angle
        abs_u = np.absolute(u_mortar)
        self.assertTrue(np.all(abs_u[1] / abs_u[0] > np.tan(setup.dilation_angle)))
        # The contact force should be zero for open fractures.
        self.assertTrue(np.all(np.isclose(contact_force, 0)))

    def test_displace_south_throughgoing_fracture(self):
        """Displace also in x direction to test same as above for sliding."""
        setup = SetupContactMechanics(
            ux_south=0.1, uy_south=0.0, ux_north=0, uy_north=0
        )
        setup.dilation_angle = np.pi / 4
        setup.fracture_endpoints = np.array([0.0, 1.0])
        u_mortar, contact_force = self._solve(setup)

        # With friction coefficient 1 and dilation angle pi/4, tangential and normal
        # displacement should be equal
        abs_u = np.absolute(u_mortar)
        self.assertTrue(np.all(np.isclose(abs_u[0], abs_u[1])))

        # The contact force in normal direction should be negative
        self.assertTrue(np.all(contact_force[1] < setup.zero_tol))

    def test_two_steps(self):
        """First pull apart, then displace horizontally."""
        setup = SetupContactMechanics(
            ux_south=0.1, uy_south=-0.09, ux_north=0, uy_north=0
        )
        setup.ux_south_initial = 0
        setup.dilation_angle = np.pi / 4
        setup.fracture_endpoints = np.array([0.0, 1.0])

        # First step
        u_mortar_0, contact_force_0 = self._solve(setup)
        # Should be open
        self.assertTrue(np.all(np.isclose(contact_force_0[1], 0)))
        self.assertTrue(np.all(u_mortar_0[1] > setup.zero_tol))
        # but no tangential displacement
        self.assertTrue(np.all(np.isclose(u_mortar_0[0], 0)))

        # Second step
        setup.time_manager.time_final = (
            1  # increase final time to enter time loop again
        )
        u_mortar_1, contact_force_1 = self._solve(setup)
        # Should be in contact (u_x > u_y on boundary):
        self.assertTrue(np.all(contact_force_1[1] < setup.zero_tol))
        # We have displaced more in the second step:
        sign = np.sign(u_mortar_1[0, 0])
        self.assertTrue(np.all(sign * (u_mortar_0[0] - u_mortar_1[0]) < setup.zero_tol))
        self.assertTrue(np.all(u_mortar_1[1] - u_mortar_0[1] > setup.zero_tol))


class SetupContactMechanics(
    tests.common.contact_mechanics_examples.ContactMechanicsExample
):
    def __init__(self, ux_south, uy_south, ux_north, uy_north):
        mesh_args = {
            "mesh_size_frac": 0.5,
            "mesh_size_min": 0.023,
            "mesh_size_bound": 0.5,
        }
        super().__init__(mesh_args, folder_name="dummy", params={"max_iterations": 25})
        self.ux_south = ux_south
        self.uy_south = uy_south
        self.ux_north = ux_north
        self.uy_north = uy_north
        self.zero_tol = 1e-8
        self.time_manager = pp.TimeManager(
            schedule=[0, 0.5], dt_init=0.5, constant_dt=True
        )

    def create_grid(self):
        """
        Method that creates and returns the MixedDimensionalGrid of a 2D domain with six
        fractures. The two sides of the fractures are coupled together with a
        mortar grid.
        """
        # Only make grid if not already available. This is necessary to avoid issues
        # with TestDilation().test_two_steps()
        if not hasattr(self, "mdg"):
            rotate_fracture = getattr(self, "rotate_fracture", False)
            endpoints = getattr(self, "fracture_endpoints", np.array([0.3, 0.7]))
            if rotate_fracture:
                self.mdg, self.box = pp.md_grids_2d.single_vertical(
                    self.mesh_args, endpoints
                )
            else:
                self.mdg, self.box = pp.md_grids_2d.single_horizontal(
                    self.mesh_args, endpoints
                )

            # Set projections to local coordinates for all fractures
            pp.contact_conditions.set_projections(self.mdg)

            self.nd = self.mdg.dim_max()

    def _bc_values(self, g):
        _, _, _, north, south, _, _ = self._domain_boundary_sides(g)
        values = np.zeros((g.dim, g.num_faces))
        # Dirty hack for the two-stage test. All other tests have time > 0
        if hasattr(self, "ux_south_initial") and self.time_manager.time < (
            1 - self.zero_tol
        ):
            values[0, south] = self.ux_south_initial
        else:
            values[0, south] = self.ux_south
        values[1, south] = self.uy_south
        values[0, north] = self.ux_north
        values[1, north] = self.uy_north
        return values.ravel("F")

    def _bc_type(self, g):
        _, _, _, north, south, _, _ = self._domain_boundary_sides(g)
        bc = pp.BoundaryConditionVectorial(g, north + south, "dir")
        # Default internal BC is Neumann. We change to Dirichlet for the contact
        # problem. I.e., the mortar variable represents the displacement on the
        # fracture faces.
        frac_face = g.tags["fracture_faces"]
        bc.is_neu[:, frac_face] = False
        bc.is_dir[:, frac_face] = True
        return bc

    def _set_parameters(self):
        super()._set_parameters()
        dilation_angle = getattr(self, "dilation_angle", 0)
        for g, d in self.mdg.subdomains(return_data=True):
            if g.dim < self.nd:

                initial_gap = getattr(self, "initial_gap", np.zeros(g.num_cells))

                d[pp.PARAMETERS]["mechanics"].update(
                    {"initial_gap": initial_gap, "dilation_angle": dilation_angle}
                )

    def before_newton_loop(self):
        """Will be run before entering a Newton loop.
        E.g.
           Discretize time-dependent quantities etc.
           Update time-dependent parameters (captured by assembly).
        """
        self._set_parameters()


if __name__ == "__main__":
    unittest.main()
