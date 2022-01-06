import numpy as np



"""
Gradient-Enhanced Partition-of-Unity Surrogate model
"""
# Might be worth making a generic base class
# Also, need to add some asserts just in case

class POUSurrogate():
    """
    Create the surrogate object

    Parameters
    ----------

    xcenter : numpy array(numsample, dim)
        Surrogate data locations
    func : numpy array(numsample)
        Surrogate data outputs
    grad : numpy array(numsample, dim)
        Surrogate data gradients
    rho : float
        Hyperparameter that controls smoothness
    delta : float
        Parameter used to regularize the distance function

    """
    def __init__(self, xcenter, func, grad, rho, delta=1e-10):
        # initialize data and parameters
        self.dim = len(xcenter[0]) # take the size of the first data point
        self.numsample = len(xcenter)

        self.xc = xcenter
        self.f = func
        self.g = grad

        self.rho = rho
        self.delta = delta

    """
    Add additional data to the surrogate

    Parameters
    ----------

    xcenter : numpy array(numsample, dim)
        Surrogate data locations
    func : numpy array(numsample)
        Surrogate data outputs
    grad : numpy array(numsample, dim)
        Surrogate data gradients
    """
    def addPoints(self, xcenter, func, grad):
        self.numsample += len(xcenter)

        self.xc.append(xcenter)
        self.f.append(func)
        self.g.append(grad)

    """
    Evaluate the surrogate as-is at the point x

    Parameters
    ----------

    x : numpy array(dim)
        Query location
    """
    def eval(self, x):

        mindist = 1e100
        xc = self.xc
        f = self.f
        g = self.g

        # exhaustive search for closest sample point, for regularization
        dists = np.zeros(self.numsample)
        for i in range(self.numsample):
            dists[i] = np.sqrt(np.dot(x-xc[i],x-xc[i]) + self.delta)
            
        mindist = min(dists)
        
        # for i in range(self.numsample):
        #     dist = np.sqrt(np.dot(x-xc[i],x-xc[i]) + self.delta)
        #     mindist = min(mindist,dist)

        numer = 0
        denom = 0

        # evaluate the surrogate, requiring the distance from every point
        for i in range(self.numsample):
            dist = np.sqrt(np.dot(x-xc[i],x-xc[i]) + self.delta)
            local = f[i] + np.dot(g[i], x-xc[i]) # locally linear approximation
            expfac = np.exp(-self.rho*(dist-mindist))
            numer += local*expfac
            denom += expfac

        return 1/denom # numer/denom

    """
    Evaluate the gradient of the surrogate at the point x, with respect to x

    Parameters
    ----------

    x : numpy array(dim)
        Query location

    """
    def evalGrad(self, x):
        sgrad = np.zeros(self.dim)

        mindist = 1e100
        xc = self.xc
        f = self.f
        g = self.g
        imindist = 1e100
        

        # exhaustive search for closest sample point, for regularization
        dists = np.zeros(self.numsample)
        for i in range(self.numsample):
            dists[i] = np.sqrt(np.dot(x-xc[i],x-xc[i]) + self.delta)
            
        mindist = min(dists)
        imindist = np.argmin(dists)

        dmindist = (1.0/mindist)*(x-xc[imindist])

        numer = 0
        denom = 0

        dnumer = np.zeros(self.dim)
        ddenom = np.zeros(self.dim)

        sum = 0

        for i in range(self.numsample):
            dist = np.sqrt(np.dot(x-xc[i],x-xc[i]) + self.delta)
            local = f[i] + np.dot(g[i], x-xc[i]) # locally linear approximation
            expfac = np.exp(-self.rho*(dist-mindist))
            numer += local*expfac
            denom += expfac        

            ddist = (1.0/np.sqrt(np.dot(x-xc[i],x-xc[i])+self.delta))*(x-xc[i])
            dlocal = g[i]
            dexp1 = -self.rho*expfac
            dexp2 = self.rho*expfac

            dnumer += expfac*dlocal + local*(dexp1*ddist + dexp2*dmindist)
            ddenom += -(1./(expfac*expfac))*(dexp1*ddist + dexp2*dmindist)

            sum += (dexp1*ddist + dexp2*dmindist)

        xgrad = (1./denom)*dnumer + numer*ddenom
        return ddenom # xgrad