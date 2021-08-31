import math
import os, sys
import time
import numpy as np
import openmdao.api as om
import plate_comp as pc

# Get options from the python file specified in a command line argument, e.g. (plate_opts.py)
# This file needs 'aeroOptions', 'warpOptions', 'optOptions', and 'uqOptions'
if len(sys.argv) <= 1:
    exit("Need to supply an options file argument")
plate_comp_opts = __import__(sys.argv[1].replace('.py', ''))
optOptions = plate_comp_opts.optOptions 
aeroOptions = plate_comp_opts.aeroOptions 
warpOptions = plate_comp_opts.warpOptions 
uqOptions = plate_comp_opts.uqOptions 

# Script to run plate optimization
ooptions = optOptions

# Print options file
fname = ooptions['prob_name']+'.txt'
resfile = open(fname, 'w')
log = open("./"+sys.argv[1], "r").read()
print(log, file = resfile)

#sys.stdout = open(os.devnull, "w")

prob = om.Problem()
prob.model.add_subsystem('bump_plate', pc.PlateComponent(), promotes_inputs=['a'])

# setup the optimization
prob.driver = om.ScipyOptimizeDriver()
prob.driver.options['optimizer'] = 'SLSQP'
prob.driver.options['debug_print'] = ['desvars','objs']
prob.driver.options['tol'] = 1e-9
prob.driver.options['maxiter'] = 200


# design vars and objectives
NV = 2*math.trunc(((1.0 - optOptions['DVFraction'])*optOptions['NX']))
ub = optOptions['DVUpperBound']*np.ones(NV)
lb = optOptions['DVLowerBound']*np.zeros(NV)
prob.model.add_design_var('a', lower=lb, upper=ub)
prob.model.add_objective('bump_plate.Cd', scaler=1)
lbc = ooptions['DCMinThick']
lba = ooptions['DCMinArea']
if ooptions['constrain_opt']:
    if ooptions['use_area_con']:
        prob.model.add_constraint('bump_plate.SA', lower = lba, scaler=1)
    else:
        prob.model.add_constraint('bump_plate.TC', lower = lbc, scaler=1)

prob.model.add_constraint('bump_plate.EQ', equals = 0.0, scaler=1)

# recording? 
prob.driver.recording_options['includes'] = ['*']
prob.driver.recording_options['record_objectives'] = True
prob.driver.recording_options['record_constraints'] = True
prob.driver.recording_options['record_desvars'] = True
prob.driver.recording_options['record_inputs'] = True
prob.driver.recording_options['record_outputs'] = True
prob.driver.recording_options['record_residuals'] = True
recorder = om.SqliteRecorder(ooptions['prob_name']+'.sql')
prob.driver.add_recorder(recorder)

prob.setup()

wc0 = time.perf_counter()
pc0 = time.process_time()

if ooptions['check_partials']:
    prob.check_partials(method = 'fd', step = 1e-6)
elif ooptions['run_once']:
    prob.run_model()
else:
    prob.run_driver()

wc1 = time.perf_counter()
pc1 = time.process_time()
wct = wc1 - wc0
pct = pc1 - pc0

#sys.stdout = sys.__stdout__

prob.model.list_inputs(values = False, hierarchical=False)
prob.model.list_outputs(values = False, hierarchical=False)

# minimum value
print('WC time = %.15g' % wct, file = resfile)
print('PC time = %.15g' % pct, file = resfile)
print('Cd = %.15g' % prob['bump_plate.Cd'], file = resfile)
if ooptions['constrain_opt']:
    if ooptions['use_area_con']:
        print('SA = %.15g' % prob['bump_plate.SA'], file = resfile)
    else:
        print('TC = ', prob['bump_plate.TC'], file = resfile)
print('Sol = ', ','.join(map(str, prob['a'])), file = resfile)