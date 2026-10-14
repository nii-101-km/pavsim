import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xcos_mini.core import Model, Engine, BlockError, AlgebraicLoopError
from xcos_mini.core import Library
_LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blocks")
LIB = Library(blocks_dir=_LIBDIR)
def blk(name):
    return LIB.instantiate(name)
import math

# T1: integrator of constant 1 -> x(t)=t
m = Model()
m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
m.add_block(blk("integrator"), "i", 100, 0)
m.add_connection("c", 0, "i", 0)
res = Engine(m, t_end=1.0, h=0.01).run()
print("T1 integrator x(1.0) =", res["i"][-1][1], "(expect ~1.0)")
assert abs(res["i"][-1][1] - 1.0) < 1e-6

# T2: feedback decay dx/dt=-x, x(0)=1 -> e^-t
m = Model()
m.add_block(blk("integrator"), "i", 0, 0); m.blocks["i"].params["initial_value"] = 1.0
m.add_block(blk("gain"), "g", 100, 0); m.blocks["g"].params["gain"] = -1.0
m.add_connection("i", 0, "g", 0); m.add_connection("g", 0, "i", 0)
res = Engine(m, t_end=1.0, h=0.001).run()
print("T2 decay x(1.0) =", res["i"][-1][1], "(expect", math.exp(-1), ")")
assert abs(res["i"][-1][1] - math.exp(-1)) < 1e-4

# T3: delay of step
m = Model()
m.add_block(blk("signal_generator"), "s", 0, 0)
m.blocks["s"].params.update({"type":"step","t0":0.0,"amplitude":1.0})
m.add_block(blk("delay"), "d", 100, 0)
m.add_connection("s", 0, "d", 0)
res = Engine(m, t_end=0.03, h=0.01).run()
print("T3 delay outputs:", [v for (t,v) in res["d"]])
assert res["d"][0][1] == 0.0 and res["d"][1][1] == 1.0

# T4: algebraic loop rejection
m = Model()
m.add_block(blk("gain"), "a", 0, 0); m.add_block(blk("gain"), "b", 100, 0)
m.add_connection("a", 0, "b", 0); m.add_connection("b", 0, "a", 0)
try:
    Engine(m, t_end=1.0, h=0.1); print("T4 FAIL: no error")
except AlgebraicLoopError as e:
    print("T4 algebraic loop rejected:", str(e)[:55], "...")

# T5: feedback through delay (valid): add = c + g; d = delay(add); g = 0.5*d
# converges to d = 1/(1-0.5) = 2
m = Model()
m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
m.add_block(blk("addition"), "a", 0, 100)
m.add_block(blk("delay"), "d", 100, 100)
m.add_block(blk("gain"), "g", 200, 100); m.blocks["g"].params["gain"] = 0.5
m.add_connection("c", 0, "a", 0)
m.add_connection("g", 0, "a", 1)
m.add_connection("a", 0, "d", 0)
m.add_connection("d", 0, "g", 0)
res = Engine(m, t_end=0.05, h=0.01).run()
dvals = [v for (t,v) in res["d"]]
print("T5 delay-feedback d outputs:", dvals, "(converging to 2)")
assert abs(dvals[0] - 0.0) < 1e-12
assert abs(dvals[-1] - 1.9375) < 1e-9

# T6: second-order oscillator dx1/dt=x2, dx2/dt=-x1 (unit circle)
m = Model()
m.add_block(blk("integrator"), "i1", 0, 0); m.blocks["i1"].params["initial_value"] = 1.0
m.add_block(blk("integrator"), "i2", 0, 100); m.blocks["i2"].params["initial_value"] = 0.0
m.add_block(blk("gain"), "gn", 100, 100); m.blocks["gn"].params["gain"] = -1.0
m.add_connection("i1", 0, "i2", 0)   # dx2/dt = x1 ... wait need -x1
# Actually: i1 integrates x2 -> x1; i2 integrates (-x1) -> x2
m2 = Model()
m2.add_block(blk("integrator"), "i1", 0, 0); m2.blocks["i1"].params["initial_value"] = 1.0
m2.add_block(blk("integrator"), "i2", 0, 100); m2.blocks["i2"].params["initial_value"] = 0.0
m2.add_block(blk("gain"), "gn", 100, 100); m2.blocks["gn"].params["gain"] = -1.0
m2.add_connection("i2", 0, "i1", 0)   # dx1/dt = x2
m2.add_connection("i1", 0, "gn", 0)   # -x1
m2.add_connection("gn", 0, "i2", 0)   # dx2/dt = -x1
res = Engine(m2, t_end=math.pi/2, h=0.001).run()
x1 = res["i1"][-1][1]; x2 = res["i2"][-1][1]
print(f"T6 oscillator at t=pi/2: x1={x1:.6f} (expect 0), x2={x2:.6f} (expect -1)")
assert abs(x1) < 1e-3 and abs(x2 + 1.0) < 1e-3

print("ALL SMOKE TESTS PASSED")
