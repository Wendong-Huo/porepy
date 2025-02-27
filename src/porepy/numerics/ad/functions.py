"""This module contains functions to be wrapped in a
:class:`~porepy.numerics.ad.operator_functions.Function` and used as part
of compound :class:`~porepy.numerics.ad.operators.Operator`, i.e. as (terms of) equations.

Some functions depend on non-ad objects. This requires that the function ``f`` be wrapped
in an ``ad.Function`` using partial evaluation:

Examples:
    >>> from functools import partial
    >>> AdFunction = pp.ad.Function(partial(f, other_parameter), "name")
    >>> equation: pp.ad.Operator = AdFunction(var) - 2 * var

    with ``var`` being some AD variable.

    Note that while the argument to ``AdFunction`` is a
    :class:`~porepy.numerics.ad.operators.Operator, the wrapping in
    ``pp.ad.Function`` implies that upon parsing,
    the argument passed to ``f`` will be an Ad_array.

"""
from __future__ import annotations

from typing import Callable

import numpy as np
import scipy.sparse as sps

import porepy as pp
from porepy.numerics.ad.forward_mode import Ad_array

__all__ = [
    "exp",
    "log",
    "sign",
    "abs",
    "l2_norm",
    "sin",
    "cos",
    "tan",
    "arcsin",
    "arccos",
    "arctan",
    "sinh",
    "cosh",
    "tanh",
    "arcsinh",
    "arccosh",
    "arctanh",
    "heaviside",
    "heaviside_smooth",
    "RegularizedHeaviside",
    "maximum",
    "characteristic_function",
]


# %% Exponential and logarithmic functions
def exp(var):
    if isinstance(var, Ad_array):
        val = np.exp(var.val)
        der = var.diagvec_mul_jac(np.exp(var.val))
        return Ad_array(val, der)
    else:
        return np.exp(var)


def log(var):
    if isinstance(var, Ad_array):
        val = np.log(var.val)
        der = var.diagvec_mul_jac(1 / var.val)
        return Ad_array(val, der)
    else:
        return np.log(var)


# %% Sign and absolute value functions and l2_norm
def sign(var):
    if not isinstance(var, Ad_array):
        return np.sign(var)
    else:
        return np.sign(var.val)


def abs(var):
    if isinstance(var, Ad_array):
        val = np.abs(var.val)
        jac = var.diagvec_mul_jac(sign(var))
        return Ad_array(val, jac)
    else:
        return np.abs(var)


def l2_norm(dim: int, var: pp.ad.Ad_array) -> pp.ad.Ad_array:
    """L2 norm of a vector variable.

    For the example of dim=3 components and n vectors, the ordering is assumed
    to be ``[u0, v0, w0, u1, v1, w1, ..., un, vn, wn]``

    Vectors satisfying ui=vi=wi=0 are assigned zero entries in the jacobi matrix

    Note:
        See module level documentation on how to wrap functions like this in ad.Function.

    Parameters:
        dim: Dimension, i.e. number of vector components.
        var: Ad operator (variable or expression) which is argument of the norm function.

    Returns:
        The norm of var with appropriate val and jac attributes.

    """

    if dim == 1:
        # For scalar variables, the cell-wise L2 norm is equivalent to
        # taking the absolute value.
        return pp.ad.functions.abs(var)
    resh = np.reshape(var.val, (dim, -1), order="F")
    vals = np.linalg.norm(resh, axis=0)
    # Avoid dividing by zero
    tol = 1e-12
    nonzero_inds = vals > tol
    jac_vals = np.zeros(resh.shape)
    jac_vals[:, nonzero_inds] = resh[:, nonzero_inds] / vals[nonzero_inds]
    # Prepare for left multiplication with var.jac to yield
    # norm(var).jac = var/norm(var) * var.jac
    dim_size = var.val.size
    # Check that size of var is compatible with the given dimension, e.g. all 'cells' have
    # the same number of values assigned
    assert dim_size % dim == 0
    size = int(dim_size / dim)
    local_inds_t = np.arange(dim_size)
    if size == 0:
        local_inds_n = np.empty(0, dtype=np.int32)
    else:
        local_inds_n = np.array(np.kron(np.arange(size), np.ones(dim)), dtype=np.int32)
    norm_jac = sps.csr_matrix(
        (jac_vals.ravel("F"), (local_inds_n, local_inds_t)),
        shape=(size, dim_size),
    )
    jac = norm_jac * var.jac
    return pp.ad.Ad_array(vals, jac)


# %% Trigonometric functions
def sin(var):
    if isinstance(var, Ad_array):
        val = np.sin(var.val)
        jac = var.diagvec_mul_jac(np.cos(var.val))
        return Ad_array(val, jac)
    else:
        return np.sin(var)


def cos(var):
    if isinstance(var, Ad_array):
        val = np.cos(var.val)
        jac = var.diagvec_mul_jac(-np.sin(var.val))
        return Ad_array(val, jac)
    else:
        return np.cos(var)


def tan(var):
    if isinstance(var, Ad_array):
        val = np.tan(var.val)
        jac = var.diagvec_mul_jac((np.cos(var.val) ** 2) ** (-1))
        return Ad_array(val, jac)
    else:
        return np.tan(var)


def arcsin(var):
    if isinstance(var, Ad_array):
        val = np.arcsin(var.val)
        jac = var.diagvec_mul_jac((1 - var.val**2) ** (-0.5))
        return Ad_array(val, jac)
    else:
        return np.arcsin(var)


def arccos(var):
    if isinstance(var, Ad_array):
        val = np.arccos(var.val)
        jac = var.diagvec_mul_jac(-((1 - var.val**2) ** (-0.5)))
        return Ad_array(val, jac)
    else:
        return np.arccos(var)


def arctan(var):
    if isinstance(var, Ad_array):
        val = np.arctan(var.val)
        jac = var.diagvec_mul_jac((var.val**2 + 1) ** (-1))
        return Ad_array(val, jac)
    else:
        return np.arctan(var)


# %% Hyperbolic functions
def sinh(var):
    if isinstance(var, Ad_array):
        val = np.sinh(var.val)
        jac = var.diagvec_mul_jac(np.cosh(var.val))
        return Ad_array(val, jac)
    else:
        return np.sinh(var)


def cosh(var):
    if isinstance(var, Ad_array):
        val = np.cosh(var.val)
        jac = var.diagvec_mul_jac(np.sinh(var.val))
        return Ad_array(val, jac)
    else:
        return np.cosh(var)


def tanh(var):
    if isinstance(var, Ad_array):
        val = np.tanh(var.val)
        jac = var.diagvec_mul_jac(np.cosh(var.val) ** (-2))
        return Ad_array(val, jac)
    else:
        return np.tanh(var)


def arcsinh(var):
    if isinstance(var, Ad_array):
        val = np.arcsinh(var.val)
        jac = var.diagvec_mul_jac((var.val**2 + 1) ** (-0.5))
        return Ad_array(val, jac)
    else:
        return np.arcsinh(var)


def arccosh(var):
    if isinstance(var, Ad_array):
        val = np.arccosh(var.val)
        den1 = (var.val - 1) ** (-0.5)
        den2 = (var.val + 1) ** (-0.5)
        jac = var.diagvec_mul_jac(den1 * den2)
        return Ad_array(val, jac)
    else:
        return np.arccosh(var)


def arctanh(var):
    if isinstance(var, Ad_array):
        val = np.arctanh(var.val)
        jac = var.diagvec_mul_jac((1 - var.val**2) ** (-1))
        return Ad_array(val, jac)
    else:
        return np.arctanh(var)


# %% Step and Heaviside functions
def heaviside(var, zerovalue: float = 0.5):
    if isinstance(var, Ad_array):
        return np.heaviside(var.val, zerovalue)
    else:
        return np.heaviside(var, zerovalue)


def heaviside_smooth(var, eps: float = 1e-3):
    """Smooth (regularized) version of the Heaviside function.

    Note:
        The analytical expression for the smooth version Heaviside function reads:
            ``H_eps(x) = (1/2) * (1 + (2/pi) * arctan(x/eps))``,
        with its derivative smoothly approximating the Dirac delta function:
            ``d(H(x))/dx = delta_eps = (1/pi) * (eps / (eps^2 + x^2))``.

        Reference: https://ieeexplore.ieee.org/document/902291

    Parameters:
        var: Input array.
        eps (optional): Regularization parameter. The function will converge to the
            Heaviside function in the limit when ``eps --> 0``. The default is ``1e-3``.

    Returns:
        Regularized heaviside function (and its Jacobian if applicable) in form of a
        Ad_array or ndarray (depending on the input).

    """
    if isinstance(var, Ad_array):
        val = 0.5 * (1 + 2 * np.pi ** (-1) * np.arctan(var.val * eps ** (-1)))
        jac = var.diagvec_mul_jac(
            np.pi ** (-1) * eps * (eps**2 + var.val**2) ** (-1)
        )
        return Ad_array(val, jac)
    else:
        return 0.5 * (1 + 2 * np.pi ** (-1) * np.arctan(var * eps ** (-1)))


class RegularizedHeaviside:
    def __init__(self, regularization: Callable):
        self._regularization = regularization

    def __call__(self, var, zerovalue: float = 0.5):
        if isinstance(var, Ad_array):
            val = np.heaviside(var.val, 0.0)
            regularization = self._regularization(var)
            jac = regularization.jac
            return Ad_array(val, jac)
        else:
            return np.heaviside(var)  # type: ignore


def maximum(
    var_0: pp.ad.Ad_array, var_1: pp.ad.Ad_array | np.ndarray
) -> pp.ad.Ad_array:
    """Ad maximum function represented as an Ad_array.

    The arguments can be either Ad_arrays or ndarrays, this duality is needed to allow
    for parsing of operators that can be taken at the current iteration (in which case
    it will parse as an Ad_array) or at the previous iteration or time step (in which
    case it will parse as a numpy array).


    Parameters:
        var_0: First argument to the maximum function.
        var_1: Second argument.

        If one of the input arguments is scalar, broadcasting will be used.


    Returns:
        The maximum of the two arguments, taken element-wise in the arrays. The return
        type is Ad_array if at least one of the arguments is an Ad_array, otherwise it
        is an ndarray. If an Ad_array is returned, the Jacobian is computed according to
        the maximum values of the Ad_arrays (so if element ``i`` of the maximum is
        picked from ``var_0``, row ``i`` of the Jacobian is also picked from the
        Jacobian of ``var_0``). If ``var_0`` is a ndarray, its Jacobian is set to zero.

    """
    # If neither var_0 or var_1 are Ad_arrays, return the numpy maximum function.
    if not isinstance(var_0, Ad_array) and not isinstance(var_1, Ad_array):
        return np.maximum(var_0, var_1)

    # Make a fall-back zero Jacobian for constant arguments.
    # EK: It is not clear if this is relevant, or if we filter out these cases with the
    # above parsing of numpy arrays. Keep it for now, but we should revisit once we
    # know clearer how the Ad-machinery should be used.
    zero_jac = 0
    if isinstance(var_0, Ad_array):
        zero_jac = sps.csr_matrix(var_0.jac.shape)
    elif isinstance(var_1, Ad_array):
        zero_jac = sps.csr_matrix(var_1.jac.shape)

    # Collect values and Jacobians.
    vals = []
    jacs = []
    for var in [var_0, var_1]:
        if isinstance(var, Ad_array):
            v = var.val
            j = var.jac
        else:
            v = var
            j = zero_jac
        vals.append(v)
        jacs.append(j)

    # If both are scalar, return same. If one is scalar, broadcast explicitly
    if isinstance(vals[0], (float, int)):
        if isinstance(vals[1], (float, int)):
            val = np.max(vals)
            return pp.ad.Ad_array(val, 0)
    else:
        # Broadcast to shape of var_1
        vals[0] = np.ones_like(vals[1]) * vals[0]
    if isinstance(vals[1], (float, int)):
        # Broadcast to shape of var_0
        vals[1] = np.ones_like(vals[0]) * vals[1]

    # Maximum of the two arrays
    inds = vals[1] >= vals[0]

    max_val = vals[0].copy()
    max_val[inds] = vals[1][inds]
    # If both arrays are constant, a 0 matrix has been assigned to jacs.
    # Return here to avoid calling copy on a number (immutable, no copy method) below.
    if isinstance(jacs[0], (float, int)):
        assert np.isclose(jacs[0], 0)
        assert np.isclose(jacs[1], 0)
        return pp.ad.Ad_array(max_val, 0)

    # Start from var_0, then change entries corresponding to inds.
    max_jac = jacs[0].copy()

    if isinstance(max_jac, sps.spmatrix):
        if not max_jac.getformat() == "csc":
            max_jac = max_jac.tocsr()
        inds = inds.nonzero()[0]
        lines = pp.matrix_operations.slice_mat(jacs[1].tocsr(), inds)
        pp.matrix_operations.merge_matrices(max_jac, lines, inds, max_jac.getformat())
    else:
        max_jac[inds] = jacs[1][inds]

    return pp.ad.Ad_array(max_val, max_jac)


def characteristic_function(tol: float, var: pp.ad.Ad_array):
    """Characteristic function of an ad variable.

    Returns 1 if ``var.val`` is within absolute tolerance = ``tol`` of zero.
    The derivative is set to zero independent of ``var.val``.

    Note:
        See module level documentation on how to wrap functions like this in ``ad.Function``.

    Parameters:
        tol: Absolute tolerance for comparison with 0 using np.isclose.
        var: Ad operator (variable or expression).

    Returns:
        The characteristic function of var with appropriate val and jac attributes.

    """
    vals = np.zeros(var.val.size)
    zero_inds = np.isclose(var.val, 0, atol=tol)
    vals[zero_inds] = 1
    jac = sps.csr_matrix(var.jac.shape)
    return pp.ad.Ad_array(vals, jac)
