import numpy as np
import scipy.sparse as sps

__all__ = ["initAdArrays", "Ad_array"]


def initAdArrays(variables):
    if not isinstance(variables, list):
        try:
            num_val = variables.size
        except AttributeError:
            num_val = 1
        return Ad_array(variables, sps.diags(np.ones(num_val)).tocsc())
    num_val = [v.size for v in variables]
    ad_arrays = []
    for i, val in enumerate(variables):
        # initiate zero jacobian
        n = num_val[i]
        jac = [sps.csc_matrix((n, m)) for m in num_val]
        # set jacobian of variable i to I
        jac[i] = sps.diags(np.ones(num_val[i])).tocsc()
        # initiate Ad_array
        jac = sps.bmat([jac])
        ad_arrays.append(Ad_array(val, jac))
    return ad_arrays


class Ad_array:
    def __init__(self, val=1.0, jac=0.0):
        self.val = val
        self.jac = jac

    def __repr__(self) -> str:
        s = f"Ad array of size {self.val.size}\n"
        s += f"Jacobian is of size {self.jac.shape} and has {self.jac.data.size} elements"
        return s

    def __add__(self, other):
        b = _cast(other)
        c = Ad_array()
        c.val = self.val + b.val
        c.jac = self.jac + b.jac
        return c

    def __radd__(self, other):
        return self.__add__(other)

    def __sub__(self, other):
        b = _cast(other).copy()
        b.val = -b.val
        b.jac = -b.jac
        return self + b

    def __rsub__(self, other):
        return -self.__sub__(other)

    def __lt__(self, other):
        return self.val < _cast(other).val

    def __le__(self, other):
        return self.val <= _cast(other).val

    def __gt__(self, other):
        return self.val > _cast(other).val

    def __ge__(self, other):
        return self.val >= _cast(other).val

    def __eq__(self, other):
        return self.val == _cast(other).val

    def __mul__(self, other):
        if not isinstance(other, Ad_array):  # other is scalar
            val = self.val * other
            if isinstance(other, np.ndarray):
                jac = self.diagvec_mul_jac(other)
            else:
                jac = self._jac_mul_other(other)
        else:
            val = self.val * other.val
            jac = self.diagvec_mul_jac(other.val) + other.diagvec_mul_jac(self.val)
        return Ad_array(val, jac)

    def __rmul__(self, other):
        if isinstance(other, Ad_array):
            # other is Ad_var, so should have called __mul__
            raise RuntimeError("Something went horrible wrong")
        val = other * self.val
        jac = self._other_mul_jac(other)
        return Ad_array(val, jac)

    def __pow__(self, other):
        if not isinstance(other, Ad_array):
            if isinstance(other, int) or isinstance(other, np.integer):
                # Standard ints and numpy scalars of integer format can be converted to
                # float in a standard way
                val = self.val ** float(other)
                jac = self.diagvec_mul_jac(other * self.val ** float(other - 1))
            elif isinstance(other, np.ndarray) and np.issubdtype(
                other.dtype, np.integer
            ):
                # Numpy arrays of integer format are converted using np.astype
                val = self.val ** other.astype(float)
                jac = self.diagvec_mul_jac(
                    other * self.val ** (other.astype(float) - 1)
                )
            else:
                # Other should be a float, or have float data type; raising to the power
                # of other should anyhow be fine. If there are more special cases not
                # yet hit upon, an error message will be given here.
                val = self.val**other
                jac = self.diagvec_mul_jac(other * self.val ** (other - 1))

        else:
            if isinstance(other.val, np.ndarray):
                # We know that other.val is a numpy array, so conversion can be done
                # using np.astype. We do this independent of the format of other; this
                # may add a slight cost, but the code becomes less complex.
                val = self.val ** other.val.astype(float)
                jac = self.diagvec_mul_jac(
                    other.val * self.val ** (other.val.astype(float) - 1)
                ) + other.diagvec_mul_jac(
                    self.val ** other.val.astype(float) * np.log(self.val)
                )
            else:
                # Other.val is presumably a float or an int, but who knows what else
                # numpy can throw at us. Make an assertion to make the code safe.
                assert isinstance(other.val, (float, int))
                val = self.val ** float(other.val)
                jac = self.diagvec_mul_jac(
                    other.val * self.val ** (float(other.val) - 1)
                ) + other.diagvec_mul_jac(
                    self.val ** float(other.val) * np.log(self.val)
                )

        return Ad_array(val, jac)

    def __rpow__(self, other):
        if isinstance(other, Ad_array):
            raise ValueError(
                "Something went horrible wrong, should have called __pow__"
            )

        # Convert self.val to float to avoid errors if self.val contains negative integers
        if isinstance(self.val, np.ndarray):
            val = other ** (self.val.astype(float))
            jac = self.diagvec_mul_jac(
                other ** (self.val.astype(float)) * np.log(other)
            )
        elif isinstance(self.val, int):
            val = other ** float(self.val)
            jac = self.diagvec_mul_jac(other ** float(self.val) * np.log(other))
        else:
            val = other**self
            jac = self.diagvec_mul_jac(other**self.val * np.log(other))
        return Ad_array(val, jac)

    def __truediv__(self, other):
        # A bit of work is needed here: Python (or numpy?) does not allow for negative
        # powers of integers, but it is allowed for floats. This leads to some special
        # cases that are treated below.
        if isinstance(other, int) or isinstance(other, np.integer):
            # Standard ints and numpy scalars of integer format can be converted to
            # float in a standard way
            return self * float(other) ** -1
        elif isinstance(other, np.ndarray) and np.issubdtype(other.dtype, np.integer):
            # Numpy arrays of integer format are converted using np.astype
            return self * other.astype(float) ** -1
        else:
            # Other should be a float, or have float data type; raising to the power of
            # other should anyhow be fine. If there are more special cases not yet hit
            # upon, an error message will be given here.
            return self * (other**-1)

    def __neg__(self):
        b = self.copy()
        b.val = -b.val
        b.jac = -b.jac
        return b

    def __len__(self):
        return len(self.val)

    def copy(self):
        b = Ad_array()
        try:
            b.val = self.val.copy()
        except AttributeError:
            b.val = self.val
        try:
            b.jac = self.jac.copy()
        except AttributeError:
            b.jac = self.jac
        return b

    def diagvec_mul_jac(self, a):
        try:
            A = sps.diags(a)
        except TypeError:
            A = a
        if isinstance(self.jac, np.ndarray):
            return np.array([A * J for J in self.jac])
        else:
            return A * self.jac

    def jac_mul_diagvec(self, a):
        try:
            A = sps.diags(a)
        except TypeError:
            A = a
        if isinstance(self.jac, np.ndarray):
            return np.array([J * A for J in self.jac])
        else:
            return self.jac * A

    def full_jac(self):
        return self.jac

    def _other_mul_jac(self, other):
        return other * self.jac

    def _jac_mul_other(self, other):
        return self.jac * other


def _cast(variables):
    if isinstance(variables, list):
        out_var = []
        for var in variables:
            if isinstance(var, Ad_array):
                out_var.append(var)
            else:
                out_var.append(Ad_array(var))
    else:
        if isinstance(variables, Ad_array):
            out_var = variables
        else:
            out_var = Ad_array(variables)
    return out_var
