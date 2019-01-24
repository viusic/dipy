from dipy.reconst.base import ReconstModel
import numpy as np
import cvxpy as cvx
from scipy.optimize import least_squares
from scipy.optimize import differential_evolution


class IVIMModel(ReconstModel):

    def __init__(self, bvals, fit_method='MIX'):
        r""" MIX framework (MIX) [1]_.

        The MIX computes the IVIM parameters.
        This algorithm uses three different optimizers. It starts with a
        differential evolutionary algorithm and fits the parameters in the
        power of exponentials. Then the fitted parameters in the first step are
        utilized to make a linear convex problem. Using a convex optimization,
        the volume fractions are determined. Then the last step is non linear
        least square fitting on all the parameters. The results of the first
        and second step are utilized as the initial values for the last step
        of the algorithm. (see [1]_ for a comparison and a through discussion).

        Parameters
        ----------
        gtab : GradientTable

        fit_method : str or callable

        Returns
        -------
        IVIM_MIX parameters

        References
        ----------
        .. [1] Farooq, Hamza, et al. "Microstructure Imaging of Crossing (MIX)
               White Matter Fibers from diffusion MRI." Scientific reports 6
               (2016).

        """

        self.maxiter = 1000  # maximum no. of iter for differential evolution
        self.xtol = 1e-8  # Tolerance for termination: nonlinear least square
        self.bvals = bvals
        self.yhat_perfusion = np.zeros(self.bvals.shape[0])
        self.yhat_diffusion = np.zeros(self.bvals.shape[0])
        self.exp_phi1 = np.zeros((self.bvals.shape[0], 2))

    def fit(self, data):
        """ Fit method of the IVIMModel model class

        Parameters
        ----------
        data : array
            The measured signal from one voxel.
            f<0.3
            D*<0.05 mm^2/s

        """
        bounds = np.array([(0.0051, 0.019), (2 * 10 ** (-6), 0.0029)])
        res_one = differential_evolution(self.stoc_search_cost, bounds,
                                         maxiter=self.maxiter, args=(data,))
        x = res_one.x
        phi = self.Phi(x)
        fe = self.cvx_fit(data, phi)
        x_fe = self.x_and_fe_to_x_fe(x, fe)
        bounds = ([0.01, 0.005, 1 * 10 ** (-6)], [0.3, 0.02,  0.003])
        res = least_squares(self.nlls_cost, x_fe, bounds=(bounds),
                            xtol=self.xtol, args=(data,))
        result = res.x
        return result

    def stoc_search_cost(self, x, signal):
        """
        Cost function for differntial evolution algorithm

        Parameters
        ----------
        x : array
        bvals
        bvecs
        G: gradient strength
        small_delta
        big_delta
        gamma: gyromagnetic ratio (2.675987 * 10 ** 8 )
        D_intra= intrinsic free diffusivity (0.6 * 10 ** 3 mircometer^2/sec)
        D_iso= isotropic diffusivity, (2 * 10 ** 3 mircometer^2/sec)

        Returns
        -------
        (signal -  S)^T(signal -  S)

        Notes
        --------
        cost function for genetic algorithm:

        .. math::

            (signal -  S)^T(signal -  S)
        """
        phi = self.Phi(x)
        return self.ivim_mix_cost_one(phi, signal)

    def ivim_mix_cost_one(self, phi, signal):  # sigma

        """
        ivim_mix_nlin
        to make cost function for differential evolution algorithm
        Parameters
        ----------
        phi:
            phi.shape = number of data points x 4
        signal:
                signal.shape = number of data points x 1
        Returns
        -------
        (signal -  S)^T(signal -  S)
        Notes
        --------
        to make cost function for genetic algorithm:
        .. math::
            (signal -  S)^T(signal -  S)
        """
        # moore-penrose
        phi_mp = np.dot(np.linalg.inv(np.dot(phi.T, phi)), phi.T)
        f = np.dot(phi_mp, signal)
        yhat = np.dot(phi, f)  # - sigma
        return np.dot((signal - yhat).T, signal - yhat)

    def cvx_fit(self, signal, phi):
        """
        Linear parameters fit using cvx

        Parameters
        ----------
        phi : array
        signal : array

        Returns
        -------
        f1, f2 (volume fractions)
        f1 = fe[0]
        f2 = fe[1]

        Notes
        --------
        cost function for differential evolution algorithm:

        .. math::

            minimize(norm((signal)- (phi*fe)))
        """

        # Create four scalar optimization variables.
        fe = cvx.Variable(2)
        # Create four constraints.
        constraints = [cvx.sum_entries(fe) == 1,
                       fe[0] >= 0.011,
                       fe[1] >= 0.011,
                       fe[0] <= 0.29,
                       fe[1] <= 0.89]

        # Form objective.
        obj = cvx.Minimize(cvx.sum_entries(cvx.square(phi * fe - signal)))

        # Form and solve problem.
        prob = cvx.Problem(obj, constraints)
        prob.solve()  # Returns the optimal value.
        return np.array(fe.value)

    def nlls_cost(self, x_fe, signal):
        """
        cost function for the least square problem

        Parameters
        ----------
        x_fe : array

        signal : array

        Returns
        -------
        sum{(signal -  phi*fe)^2}

        Notes
        --------
        cost function for the least square problem

        .. math::

            sum{(signal -  phi*fe)^2}
        """

        x, fe = self.x_fe_to_x_and_fe(x_fe)
        fe1 = np.array([fe, 1 - fe])
        phi = self.Phi(x)
        return np.sum((np.dot(phi, fe1) - signal) ** 2)

    def x_fe_to_x_and_fe(self, x_fe):
        x = np.zeros(2)
        fe = x_fe[0]
        x = x_fe[1:3]
        return x, fe

    def x_and_fe_to_x_fe(self, x, fe):
        x_fe = np.zeros(3)
        x_fe[0] = fe[0]
        x_fe[1:3] = x
        return x_fe

    def Phi(self, x):
        self.yhat_perfusion = self.bvals * x[0]
        self.yhat_diffusion = self.bvals * x[1]
        self.exp_phi1[:, 0] = np.exp(-self.yhat_perfusion)
        self.exp_phi1[:, 1] = np.exp(-self.yhat_diffusion)
        return self.exp_phi1
