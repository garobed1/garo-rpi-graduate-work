import numpy as np
import copy
import collections

from optimization.optimizers import optimize
from optimization.robust_objective import RobustSampler

from smt.utils.options_dictionary import OptionsDictionary

import openmdao.api as om
from openmdao.utils.mpi import MPI


class OptSubproblem():
    """
    Base class that defines a generic optimization subproblem, i.e. 

    Quadratic Trust Region model
    Surrogate Trust model
    Low order UQ approximation

    These may be solved in a subregion of the domain (trust radius), or the whole
    thing. Either way, the results of solving this should be compared to some 
    "truth" model, and various parameters should be updated (such as trust radius,
    surrogate sampling, etc.)



    Needs:

    Optimizer with settings
    Subdomain definition
    Appropriate constraints to handle subdomain if used
    Access to SMT surrogate methods
    Access to adaptive refinement criteria, sampling

    """
    def __init__(self, prob_model=None, prob_truth=None, **kwargs):
        """
        Initialize attributes
        """
        self.name = 'subopt_object'
        self.pathname = None
        self.comm = None

        # OM problems to be treated as submodel and truth. Could be same
        # regardless, they need the same design variable inputs, outputs, etc.
        self.prob_model = prob_model
        self.prob_truth = prob_truth

        # list of names of the ins, outs, and cons of the actual problem. 
        # the methods here may add more constraints or modify the objective, for example
        self.prob_ins = None
        self.prob_outs = None
        self.prob_cons = None

        self.options = OptionsDictionary()

        self.outer_iter = 0
        self.truth_iters = 0
        self.model_iters = 0
        self.break_iters = []

        self.setup_completed = False

        self.result_cur = None

        self.pred = 0 # predicted reduction
        self.ared = 0 # actual/approximate reduction

        self._declare_options()
        self.options.update(kwargs)

    def _declare_options(self):
        declare = self.options.declare
        
        declare(
            "gtol", 
            default=1e-6, 
            types=float,
            desc="Maximum allowable optimality at sub-optimization solutions"
        )

        declare(
            "ctol", 
            default=1e-5, 
            types=float,
            desc="Maximum allowable feasability/constraint violation at sub-optimization solutions"
        )

        declare(
            "stol", 
            default=1e-5, 
            types=float,
            desc="step size tolerance"
        )

        declare(
            "max_iter", 
            default=50, 
            types=int,
            desc="Maximum number of outer iterations"
        )

        # NOTE: mainly useful for trust radius, but can be useful for approximate truth as well
        declare(
            "eta", 
            default=0.25, 
            types=float,
            desc="main acceptance parameter for proposed step"
        )

        declare(
            "eta_1", 
            default=0.25, 
            types=float,
            desc="acceptance threshold for shrinking radius"
        )

        declare(
            "eta_2", 
            default=0.75, 
            types=float,
            desc="acceptance threshold for increasing radius"
        )
        # NOTE: Kouri uses \omega = 0.75
        declare(
            "omega",
            default=1.0,
            types=float,
            desc="exp factor for the truth approximation error tolerance, range (0,1)"
        )

        declare(
            "solve_subproblem_with_driver", 
            default=True, 
            types=bool,
            desc="Whether or not we solve the subproblem with the OM driver or an external method (trust region)"
        )
        declare(
            "approximate_truth", 
            default=False, 
            types=bool,
            desc="Run as if the truth function is being approximated, increase accuracy as needed according to (4.8) in Kouri 2014"
        )
        declare(
            "approximate_truth_max", 
            default=5000, 
            types=int,
            desc="maximum allowable truth level if we're approximating the truth value"
        )

        declare(
            "print", 
            default=1, 
            types=int,
            desc="Print level for outer iterations"
        )


    def set_model(self, model):
        self.prob_model = model
        self.setup_completed = False


    def set_truth(self, truth):
        self.prob_truth = truth
        self.setup_completed = False


    def setup_optimization(self):
        
        # assume that each problem has been set up appropriately
        if self.prob_model is None or self.prob_truth is None:
            print(f"{self.name}: Both the model and truth systems need to be assigned before setting up!")
            return

        self._setup_final() # components may get added here

        # call om setup on them here
        self.prob_model.setup()
        self.prob_truth.setup()

        model_ins = list(self.prob_model.model.get_design_vars().keys())
        truth_ins = list(self.prob_truth.model.get_design_vars().keys())

        model_outs = list(self.prob_model.model.get_objectives().keys())
        truth_outs = list(self.prob_truth.model.get_objectives().keys())

        model_cons = list(self.prob_model.model.get_constraints().keys())
        truth_cons = list(self.prob_truth.model.get_constraints().keys())

        assert(collections.Counter(model_ins) == collections.Counter(truth_ins))
        assert(collections.Counter(model_outs) == collections.Counter(truth_outs))
        # assert(collections.Counter(model_cons) == collections.Counter(truth_cons))
        
        self.prob_ins = truth_ins
        self.prob_outs = truth_outs
        self.prob_cons = truth_cons

        
        self.setup_completed = True
        
    def _setup_final(self):
        pass

    def solve_full(self):
        """
        Solve the overall optimization problem by solving successive subproblems

        The manner in which this is done is determined by derived classes
        """

        pass

    def _solve_subproblem(self, zk, radius=-1., solve_with_driver=1):
        """
        Find s_k that may update z_k to z_{k+1} = z_k + s_k by solving the subproblem

        zk : dict
            initial guess in OM dict format

        radius: float
            trust radius for the subproblem. if negative, don't enforce a trust radius

        solve_with_driver: int
            if we have a trust radius, choose how we implement it in the subproblem
            solve using the attached OpenMDAO driver (in which case, any trust)
            0 : don't use driver (not implemented)
            1 : use driver with a nonlinear constraint
            2 : use driver with box/bound constraints (not implemented)

        """

        prob = self.prob_model

        # zk is initial condicition
        i = 0
        if MPI:
            zk = prob.comm.bcast(zk, root=0)
        
        for name, meta in prob.driver._designvars.items():
            size = meta['size']
            # prob.set_val(name, zk[i:i + size])
            val = zk[name]
            if size == 1:
                val = zk[name][0]
            prob.set_val(name, val)
            i += size

        # in this case, run the driver as is
        if radius < 0.:
            self.prob_model.run_driver()

        # in this case, add a bound radius constraint 
        elif solve_with_driver == 1 and radius >= 0.0:
            #NOTE: the model needs the specific TrustBound component as a subsystem

            self.prob_model.model.trust.set_center(zk)
            self.prob_model.model.trust.set_radius(radius)
            self.prob_model.comm.Barrier()
            self.prob_model.run_driver()
        
        # in this case, use an outside implementation of a trust subproblem
        elif not solve_with_driver and radius >= 0.0:
            raise Exception("Using external subproblem optimizer not implemented")
        
        # invalid case, no way of solving full optimization without driver
        else:
            raise Exception("Full optimization should be done with OM driver")

        # count number of function calls
        if solve_with_driver:
            self.break_iters.append(self.prob_model.driver.iter_count)
            self.model_iters += self.prob_model.model.stat.get_fidelity()*self.prob_model.driver.iter_count
        else:
            raise Exception("Non-driver subproblem not implemented")


    def _eval_truth(self, zk):
        """
        At certain points of the optimization, evaluate the "truth" model for comparison
        or approval, and use the result to take action
        """

        prob = self.prob_truth

        i = 0
        if MPI:
            prob.comm.bcast(zk, root=0)
        
        for name, meta in prob.driver._designvars.items():
            size = meta['size']
            # prob.set_val(name, zk[i:i + size])
            val = zk[name]
            if size == 1:
                val = zk[name][0]
            prob.set_val(name, val)
            i += size


        # if we're using an approximate truth, we need to determine an appropriate uq level
        # error est \theta_k \leq \eta min(pred_k, r_k), where pred_k is predicted reduction

        # so compute pred before coming here
        # and attach an error estimate to prob_truth
        if self.options["approximate_truth"]:
            eta = min(self.options["eta_1"], 1. - self.options["eta_2"])
            # min(pred, r), use pred
            tol = eta * self.pred
            tol ** (1./self.options["omega"])
            
            pass
            

        self.prob_truth.run_model()

        #TODO: Record number of evaluations (should come from the eventual component)
        # 1 unless overriden by uncertain component
        self.truth_iters += self.prob_truth.model.stat.get_fidelity()

    # def _array_to_model_set



"""
Fully-solve an optimization at a low fidelity, validate, refine, and fully solve
again. Ad hoc approach suggested by Jason Hicken

"""
class SequentialFullSolve(OptSubproblem):
    def __init__(self, **kwargs):


        super().__init__(**kwargs)


    def _declare_options(self):
        
        super()._declare_options()
        
        declare = self.options.declare
        
        declare(
            "ftol", 
            default=1e-6, 
            types=float,
            desc="Maximum allowable difference between truth and model values at sub-optimizations"
        )

        declare(
            "flat_refinement", 
            default=5, 
            types=int,
            desc="Flat refinement amount to apply at each outer iter"
        )

        declare(
            "use_truth_to_train", 
            default=False, 
            types=bool,
            desc="If the model uses a surrogate, add the truth evaluations to its training data"
        )
        
        declare(
            "ref_strategy", 
            default=0, 
            types=int,
            desc="""
                 0: Flat refinement
                 1: Refine by first-order proximity to 0
                 """
        )

    def solve_full(self):

        ftol = self.options['ftol']
        gtol = self.options['gtol']
        miter = self.options['max_iter']

        ferr = 1e6
        gerr = 1e6

        zk = self.prob_model.driver.get_design_var_values()
        # DICT TO ARRAY (OR NOT)

        fail = 0
        k = 0

        fetext = '-'
        getext = '-'

        gerr0 = 0
        # we assume that fidelity belongs to the top level system
        # calling it stat for now
        reflevel = self.prob_model.model.stat.get_fidelity()
        refjump = self.options["flat_refinement"]
        #TODO: Need constraint conditions as well

        fail = 1
        while (ferr > ftol or gerr > gtol) and (k < miter):

            if self.options["print"]:
                print("\n")
                print(f"Outer Iteration {k} ")
                print(f"-------------------")
                print(f"    OBJ ERR: {fetext}")
                # Add constraint loop as well
                print(f"    -")
                print(f"    GRD ERR: {getext}")
                print(f"    Fidelity: {reflevel}")
                
                self.prob_model.list_problem_vars()
            
                print(f"    Solving subproblem...")
            #Complete a full optimization
            fmod_cent = copy.deepcopy(self.prob_model.get_val(self.prob_outs[0]))
            self._solve_subproblem(zk)
            
            fmod_cand = copy.deepcopy(self.prob_model.get_val(self.prob_outs[0]))



            #Eval Truth
            if self.options["print"]:
                print(f"    Computing truth model...")

            zk = self.prob_model.driver.get_design_var_values()

            # hold on to original truth value
            ftru_cent = copy.deepcopy(self.prob_truth.get_val(self.prob_outs[0]))
            self.pred = fmod_cent - fmod_cand

            self._eval_truth(zk)



            ftru_cand = copy.deepcopy(self.prob_truth.get_val(self.prob_outs[0]))

            # this needs to be the lagrangian gradient with constraints
            # gmod = self.prob_model.compute_totals(return_format='array')
            gtru = self.prob_truth.compute_totals(return_format='array')

            ferr = abs(fmod_cand-ftru_cand)

            # perhaps instead we try the condition from Kouri (2013)?
            # not really, it uses the model gradient, which is known to be
            # close to the true gradient as a result of the algorithm assumptions

            gerr = np.linalg.norm(gtru)

            if k == 0:
                gerr0 += gerr
                grange = gerr0 - gtol

            fetext = str(ferr)
            getext = str(gerr)
            # ferr = 
            # gerr = c

            #If f or g metrics are not met, 
            if gerr < gtol:
                fail = 0
                break

            """
            This still doesn't quite work, even getting close to the truth the smaller 
            the gradient, we're still using different points, and the two models don't
            agree
            """
            if(self.options["ref_strategy"]):
                grel = gerr-gtol
                gclose = 1. - abs(grel/grange)
                rmin = self.options["flat_refinement"] #minimum improvement
                rcap = self.prob_truth.model.stat.get_fidelity()

                fac = gclose - reflevel/rcap

                refjump = rmin + max(0, int(fac*rcap))

            # grab sample data from the truth model if we are using a surrogate
            if self.prob_model.model.stat.surrogate and self.options["use_truth_to_train"]:
                truth_eval = self.prob_truth.model.stat.sampler.current_samples
                if self.options["print"]:
                    print(f"    Refining model with {truth_eval['x'].shape[0]} validation points")
                self.prob_model.model.stat.refine_model(truth_eval)
                reflevel = self.prob_model.model.stat.xtrain_act.shape[0]
            else:
                if self.options["print"]:
                    print(f"    Refining model by adding {refjump} points to evaluation")
                self.prob_model.model.stat.refine_model(refjump)
                reflevel += refjump

            k += 1            
            self.outer_iter = k

        if fail:
            succ = f'unsuccessfully, true gradient norm: {getext}'
        else:
            succ = 'successfully!'

        zk = self.prob_model.driver.get_design_var_values()
        self.result_cur = zk

        print("\n")
        print(f"Optimization terminated {succ}")
        print(f"-------------------")
        print(f"    Outer Iterations: {self.outer_iter}")
        # Add constraint loop as well
        print(f"    -")
        print(f"    Final design vars: {zk}")
        print(f"    Final objective: {ftru_cand}")
        print(f"    Final gradient norm: {getext}")
        print(f"    Final model error: {fetext}")
        print(f"    Final model level: {reflevel}")

        print(f"    Total model samples: {self.model_iters}")
        print(f"    Total truth samples: {self.truth_iters}")
        print(f"    Total samples: {self.model_iters + self.truth_iters}")