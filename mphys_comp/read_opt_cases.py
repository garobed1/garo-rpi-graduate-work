import matplotlib.pyplot as plt
import openmdao.api as om
import numpy as np
import argparse

# parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('-d', '--optcase', action='store', help = 'case file name')

args = parser.parse_args()
optcase = args.optcase

# Instantiate your CaseReader
cr = om.CaseReader(optcase)

# Get driver cases (do not recurse to system/solver cases)
driver_cases = cr.get_cases('driver', recurse=False)

# Plot the path the design variables took to convergence
# Note that there are two lines in the right plot because "Z"
# contains two variables that are being optimized
dv_values = []
obj_values = []
con_values = []

# import pdb; pdb.set_trace()
for case in driver_cases:
    dv_values.append(case.get_design_vars()['dv_struct_TRUE'][1])
    obj_values.append(case.get_objectives()['test.mass'])
    con_values.append(case.get_constraints()['test.stresscon'])

# import pdb; pdb.set_trace()
fig, (ax1, ax2, ax3) = plt.subplots(3, 1)
fig.subplots_adjust(left=None, bottom=None, right=None, top=None, wspace=0.5, hspace=None)
fig.set_size_inches(6, 12)
# import pdb; pdb.set_trace()
ax1.plot(np.arange(len(dv_values)), np.array(obj_values))
ax1.set(ylabel='Mass Objective', title=f'Optimization History, {optcase[10:-4]}')
ax1.grid()

ax2.plot(np.arange(len(dv_values)), np.array(con_values))
ax2.set(ylabel='Max Stress KS Constraint')
ax2.grid()

ax3.plot(np.arange(len(dv_values)), np.array(dv_values))
ax3.set(xlabel='Iterations', ylabel='Thickness DV 2')
ax3.grid()

plt.savefig(f'{optcase[:-4]}.png', bbox_inches='tight')

# plt.show()