"""Generate genuine OctaLink JSON block-diagram models for robotics areas.

Every model uses only C-exportable blocks (signal flow: sources, sums, gains,
trig, integrators, transfer functions, state space, PID, saturation, relay,
switch, mux/demux, unit delay, ZOH, scopes) so each can be verified with:
  (a) headless Python/Octave simulation (`--run` / `simulate_document`)
  (b) C99 codegen + native GCC run vs engine truth (`c_export.export_c_model`)
  (c) Octave PNG export of the sink traces.

Run:  python build_models.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
EXAMPLES.mkdir(exist_ok=True)

_version = "4.0"
_dt = "0.01"
_stop = "8"
_counter = [0]


def new_id():
    _counter[0] += 1
    return _counter[0]


def block(kind, name=None, x=0, y=0, **params):
    return {"id": new_id(), "type": kind, "name": name or kind,
            "x": float(x), "y": float(y),
            "params": {k: str(v) for k, v in params.items()}}


def connect(src, dst, src_port=0, dst_port=0):
    return {"from_block": src, "from_port": src_port,
            "to_block": dst, "to_port": dst_port}


def model(stop_time, dt, blocks, wires, description=""):
    return {"version": _version, "stop_time": str(stop_time), "dt": str(dt),
            "solver": "rk4", "description": description,
            "root": {"blocks": blocks, "wires": wires}}


def write(name, doc):
    path = EXAMPLES / f"{name}.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {path} ({len(doc['root']['blocks'])} blocks, "
          f"{len(doc['root']['wires'])} wires)")
    return path


# ---------------------------------------------------------------------------
# 1. Path following / Stanley steering controller
#    delta = e_psi + atan(k_e * e_lat / v_x), saturated.
# ---------------------------------------------------------------------------
def path_following_stanley():
    b = block
    h_err = b("Constant", "heading_error", value=0.2, y=0)
    cte = b("Constant", "cross_track_error", value=0.5, y=40)
    v = b("Constant", "speed", value=2.0, y=80)
    ke = b("Constant", "stanley_gain", value=1.5, y=120)
    g1 = b("Gain", "k_e*cte", gain=1.5, x=140, y=40)          # cte -> k_e*cte
    g2 = b("Gain", "div_by_v", gain=0.5, x=140, y=80)          # -> k_e*cte/v
    atan = b("Trig", "atan(cte/v)", operator="atan", x=280, y=60)
    s = b("Sum", "steering_raw", signs="++", x=420, y=60)
    sat = b("Saturation", "steering_cmd", lower_limit=-0.6,
            upper_limit=0.6, x=560, y=60)
    sc = b("Scope", "Stanley steering command", x=700, y=60)
    m = model(8, 0.01,
              [h_err, cte, v, ke, g1, g2, atan, s, sat, sc],
              [connect(ctte_id if False else cte["id"], g1["id"]),
               connect(g1["id"], g2["id"]),
               connect(g2["id"], atan["id"]),
               connect(h_err["id"], s["id"], dst_port=0),
               connect(atan["id"], s["id"], dst_port=1),
               connect(s["id"], sat["id"]),
               connect(sat["id"], sc["id"])],
              "Stanley path-following steering law: delta = e_psi + atan(k_e*e_lat/v).")
    write("robotics_path_following_stanley", m)


# ---------------------------------------------------------------------------
# 2. Multi-loop (cascade) PID position control
#    outer position PI -> velocity ref; inner velocity PID -> motor torque;
#    plant: torque -> 1st-order motor -> velocity -> Integrator -> position.
# ---------------------------------------------------------------------------
def multi_loop_pid():
    b = block
    pos_ref = b("Constant", "position_ref", value=1.0, y=0)
    sum_pos = b("Sum", "position_error", signs="+-", x=140, y=0)
    pid_out = b("PID Controller", "outer position PI", Kp=1.0, Ki=0.5,
                Kd=0.0, N=100.0, x=280, y=0)
    sum_vel = b("Sum", "velocity_error", signs="+-", x=280, y=120)
    pid_in = b("PID Controller", "inner velocity PID", Kp=10.0, Ki=5.0,
               Kd=1.0, N=100.0, x=420, y=120)
    sat = b("Saturation", "torque_limit", lower_limit=-5.0, upper_limit=5.0,
            x=560, y=120)
    motor = b("Transfer Fcn", "motor 1/(10s+1)", numerator="[1]",
              denominator="[10, 1]", x=700, y=120)
    integ = b("Integrator", "velocity->position", initial_condition=0.0,
              x=840, y=120)
    mux = b("Mux", "signals", inputs=3, x=980, y=40)
    sc = b("Scope", "Cascade position tracking", x=1120, y=40)
    m = model(8, 0.01,
              [pos_ref, sum_pos, pid_out, sum_vel, pid_in, sat, motor, integ,
               mux, sc],
              [connect(pos_ref["id"], sum_pos["id"], dst_port=0),
               connect(integ["id"], sum_pos["id"], dst_port=1),
               connect(sum_pos["id"], pid_out["id"]),
               connect(pid_out["id"], sum_vel["id"], dst_port=0),
               connect(motor["id"], sum_vel["id"], dst_port=1),
               connect(sum_vel["id"], pid_in["id"]),
               connect(pid_in["id"], sat["id"]),
               connect(sat["id"], motor["id"]),
               connect(motor["id"], integ["id"]),
               connect(pos_ref["id"], mux["id"], dst_port=0),
               connect(integ["id"], mux["id"], dst_port=1),
               connect(motor["id"], mux["id"], dst_port=2),
               connect(mux["id"], sc["id"])],
              "Cascade PID: outer position loop commands velocity, inner loop "
              "commands motor torque through a 1st-order plant.")
    write("robotics_multi_loop_pid", m)


# ---------------------------------------------------------------------------
# 3. Adaptive Cruise Control (ACC)
#    spacing = lead_pos - ego_pos; desired_gap = d0 + v*headway;
#    spacing_err -> PI -> accel (saturated) -> Integrator -> vel -> pos.
# ---------------------------------------------------------------------------
def acc_adaptive_cruise():
    b = block
    lead_speed = b("Constant", "lead_speed", value=20.0, y=0)
    lead_pos = b("Integrator", "lead position", initial_condition=50.0, y=0)
    headway = b("Constant", "headway_time", value=1.5, y=80)
    d0 = b("Constant", "standstill_gap", value=5.0, y=120)
    prod = b("Product", "v*headway", ops="**", x=140, y=80)
    gap = b("Sum", "desired_gap", signs="++", x=140, y=140)
    ego_vel = b("Integrator", "ego velocity", initial_condition=10.0, y=220)
    ego_pos = b("Integrator", "ego position", initial_condition=0.0, y=260)
    spacing = b("Sum", "spacing", signs="+-", x=140, y=220)
    spacing_err = b("Sum", "spacing_error", signs="+-", x=140, y=280)
    pid = b("PID Controller", "ACC PI", Kp=0.6, Ki=0.2, Kd=0.0, N=100.0,
            x=280, y=260)
    accel = b("Saturation", "accel_cmd", lower_limit=-3.0, upper_limit=2.0,
              x=420, y=260)
    mux = b("Mux", "signals", inputs=4, x=560, y=140)
    sc = b("Scope", "ACC speed and spacing", x=700, y=140)
    m = model(10, 0.01,
              [lead_speed, lead_pos, headway, d0, prod, gap, ego_vel, ego_pos,
               spacing, spacing_err, pid, accel, mux, sc],
              [connect(lead_speed["id"], lead_pos["id"]),
               connect(ego_vel["id"], prod["id"], dst_port=0),
               connect(headway["id"], prod["id"], dst_port=1),
               connect(d0["id"], gap["id"], dst_port=0),
               connect(prod["id"], gap["id"], dst_port=1),
               connect(lead_pos["id"], spacing["id"], dst_port=0),
               connect(ego_pos["id"], spacing["id"], dst_port=1),
               connect(spacing["id"], spacing_err["id"], dst_port=0),
               connect(gap["id"], spacing_err["id"], dst_port=1),
               connect(spacing_err["id"], pid["id"]),
               connect(pid["id"], accel["id"]),
               connect(accel["id"], ego_vel["id"]),
               connect(ego_vel["id"], ego_pos["id"]),
               connect(ego_vel["id"], mux["id"], dst_port=0),
               connect(lead_speed["id"], mux["id"], dst_port=1),
               connect(spacing["id"], mux["id"], dst_port=2),
               connect(spacing_err["id"], mux["id"], dst_port=3),
               connect(mux["id"], sc["id"])],
              "Adaptive cruise control: regulate spacing to d0 + v*headway.")
    write("robotics_acc_adaptive_cruise", m)


# ---------------------------------------------------------------------------
# 4. UAV mixer (quadrotor) with motor first-order lag and saturation
#    mixing matrix maps [thrust, roll, pitch, yaw] -> 4 motor commands.
# ---------------------------------------------------------------------------
def uav_mixer():
    b = block
    thrust = b("Constant", "thrust", value=10.0, y=0)
    roll = b("Constant", "roll_cmd", value=0.5, y=40)
    pitch = b("Constant", "pitch_cmd", value=0.3, y=80)
    yaw = b("Constant", "yaw_cmd", value=0.1, y=120)
    mux = b("Mux", "mix_inputs", inputs=4, x=140, y=60)
    mix = b("Gain", "mixing_matrix",
            gain="[1 -1 1 -1; 1 1 1 1; 1 1 -1 -1; 1 -1 -1 1]",
            multiplication="Matrix(K*u)", x=280, y=60)
    demux = b("Demux", "motor_commands", outputs=4, x=420, y=60)
    motors = []
    sat = []
    for i in range(4):
        motors.append(b("Transfer Fcn", f"motor{i+1}_lag",
                        numerator="[1]", denominator="[0.05, 1]",
                        x=560, y=20 + i * 40))
        sat.append(b("Saturation", f"motor{i+1}_cmd",
                     lower_limit=0.0, upper_limit=20.0,
                     x=700, y=20 + i * 40))
    out_mux = b("Mux", "motor_outputs", inputs=4, x=840, y=60)
    sc = b("Scope", "UAV mixer motor commands", x=980, y=60)
    blocks = [thrust, roll, pitch, yaw, mux, mix, demux] + motors + sat + \
        [out_mux, sc]
    wires = [connect(thrust["id"], mux["id"], dst_port=0),
             connect(roll["id"], mux["id"], dst_port=1),
             connect(pitch["id"], mux["id"], dst_port=2),
             connect(yaw["id"], mux["id"], dst_port=3),
             connect(mux["id"], mix["id"]),
             connect(mix["id"], demux["id"])]
    for i in range(4):
        wires.append(connect(demux["id"], motors[i]["id"], src_port=i,
                             dst_port=0))
        wires.append(connect(motors[i]["id"], sat[i]["id"]))
        wires.append(connect(sat[i]["id"], out_mux["id"], dst_port=i))
    wires.append(connect(out_mux["id"], sc["id"]))
    m = model(6, 0.01, blocks, wires,
              "Quadrotor mixer: [thrust,roll,pitch,yaw] -> 4 motors via mixing "
              "matrix, 1st-order motor lag, output saturation.")
    write("robotics_uav_mixer", m)


# ---------------------------------------------------------------------------
# 5. Marine LOS (line-of-sight) guidance + heading autopilot
#    cte/L -> Trig atan -> los_angle; los - heading -> PID -> rudder ->
#    1st-order vessel -> heading Integrator.
# ---------------------------------------------------------------------------
def marine_los():
    b = block
    cte = b("Constant", "cross_track_error", value=2.0, y=0)
    gain_l = b("Gain", "cte/L (L=10)", gain=0.1, x=140, y=25)
    los = b("Trig", "los_angle", operator="atan", x=280, y=25)
    sum_hdg = b("Sum", "heading_error", signs="+-", x=280, y=100)
    pid = b("PID Controller", "heading PID", Kp=2.0, Ki=0.5, Kd=0.3, N=100.0,
            x=420, y=100)
    rudder = b("Saturation", "rudder", lower_limit=-0.4, upper_limit=0.4,
               x=560, y=100)
    vessel = b("Transfer Fcn", "vessel heading 1/(2s+1)", numerator="[1]",
               denominator="[2, 1]", x=700, y=100)
    heading = b("Integrator", "heading", initial_condition=0.0, x=840, y=100)
    speed = b("Constant", "speed", value=3.0, y=180)
    sin = b("Trig", "sin(heading)", operator="sin", x=840, y=180)
    prod = b("Product", "speed*sin(hdg)", ops="**", x=980, y=180)
    mux = b("Mux", "signals", inputs=5, x=1120, y=120)
    sc = b("Scope", "Marine LOS heading + cross-track", x=1260, y=120)
    m = model(10, 0.01,
              [cte, gain_l, los, sum_hdg, pid, rudder, vessel, heading,
               speed, sin, prod, mux, sc],
              [connect(cte["id"], gain_l["id"]),
               connect(gain_l["id"], los["id"]),
               connect(los["id"], sum_hdg["id"], dst_port=0),
               connect(heading["id"], sum_hdg["id"], dst_port=1),
               connect(sum_hdg["id"], pid["id"]),
               connect(pid["id"], rudder["id"]),
               connect(rudder["id"], vessel["id"]),
               connect(vessel["id"], heading["id"]),
               connect(heading["id"], sin["id"]),
               connect(speed["id"], prod["id"], dst_port=0),
               connect(sin["id"], prod["id"], dst_port=1),
               connect(cte["id"], mux["id"], dst_port=0),
               connect(los["id"], mux["id"], dst_port=1),
               connect(heading["id"], mux["id"], dst_port=2),
               connect(rudder["id"], mux["id"], dst_port=3),
               connect(prod["id"], mux["id"], dst_port=4),
               connect(mux["id"], sc["id"])],
              "Marine line-of-sight guidance: los=atan(cte/L) drives a heading "
              "autopilot over a 1st-order vessel plant.")
    write("robotics_marine_los", m)


# ---------------------------------------------------------------------------
# 6. AUV reduced 3-DOF (surge, heave, yaw): PI-controlled 1st-order plants
#    with position integrators, all channels muxed to one scope.
# ---------------------------------------------------------------------------
def auv_3dof():
    b = block
    blocks = []
    wires = []
    refs = [("surge", 1.5), ("heave", 0.0), ("yaw", 0.0)]
    gains = [("surge", 0.8, 0.2), ("heave", 1.0, 0.3), ("yaw", 1.2, 0.4)]
    dens = [("surge", "[3, 1]"), ("heave", "[4, 1]"), ("yaw", "[2, 1]")]
    channel_signals = []
    for i, ((name, ref), (_, kp, ki), (_, den)) in enumerate(zip(refs, gains,
                                                                 dens)):
        col = i * 170
        ref_blk = b("Constant", f"{name}_ref", value=ref, x=col, y=0)
        err = b("Sum", f"{name}_error", signs="+-", x=col + 140, y=0)
        pid = b("PID Controller", f"{name}_PI", Kp=kp, Ki=ki, Kd=0.0, N=100.0,
                x=col + 280, y=0)
        sat = b("Saturation", f"{name}_cmd", lower_limit=-2.0,
                upper_limit=2.0, x=col + 420, y=0)
        plant = b("Transfer Fcn", f"{name}_plant", numerator="[1]",
                  denominator=den, x=col + 560, y=0)
        pos = b("Integrator", f"{name}_position", initial_condition=0.0,
                x=col + 700, y=0)
        blocks += [ref_blk, err, pid, sat, plant, pos]
        channel_signals += [ref_blk, plant, pos]
        wires += [connect(ref_blk["id"], err["id"], dst_port=0),
                  connect(pos["id"], err["id"], dst_port=1),
                  connect(err["id"], pid["id"]),
                  connect(pid["id"], sat["id"]),
                  connect(sat["id"], plant["id"]),
                  connect(plant["id"], pos["id"])]
    # Combine all three channels (ref, plant output, position each) into one
    # scope via a final 9-input mux (Mux has a single output, so feed the
    # three raw signals directly instead of chaining per-channel muxes).
    big = b("Mux", "all_channels", inputs=9, x=840 + 3 * 170, y=0)
    sc = b("Scope", "AUV 3-DOF surge/heave/yaw", x=980 + 3 * 170, y=0)
    blocks += [big, sc]
    mi = 0
    for sig in channel_signals:
        wires.append(connect(sig["id"], big["id"], dst_port=mi))
        mi += 1
    wires.append(connect(big["id"], sc["id"]))
    m = model(8, 0.01, blocks, wires,
              "AUV reduced 3-DOF: three decoupled PI-controlled 1st-order "
              "plants with position integrators (surge, heave, yaw).")
    write("robotics_auv_3dof", m)


# ---------------------------------------------------------------------------
# 7. Ground vehicle kinematic (unicycle/bicycle) model
#    x_dot = v*cos(psi), y_dot = v*sin(psi), psi_dot = v*tan(delta)/wheelbase
# ---------------------------------------------------------------------------
def ground_vehicle():
    b = block
    vel = b("Constant", "velocity", value=2.0, y=0)
    steer = b("Constant", "steering_angle", value=0.2, y=60)
    wb = b("Constant", "wheelbase", value=2.5, y=120)
    tan = b("Trig", "tan(steer)", operator="tan", x=140, y=60)
    prod1 = b("Product", "v*tan(delta)", ops="**", x=140, y=120)
    gain_wb = b("Gain", "1/wheelbase", gain=0.4, x=280, y=120)
    yaw_rate = b("Integrator", "heading", initial_condition=0.0, x=420, y=60)
    cos = b("Trig", "cos(heading)", operator="cos", x=420, y=180)
    sin = b("Trig", "sin(heading)", operator="sin", x=420, y=240)
    prod_x = b("Product", "v*cos(psi)", ops="**", x=560, y=180)
    prod_y = b("Product", "v*sin(psi)", ops="**", x=560, y=240)
    x_int = b("Integrator", "x position", initial_condition=0.0, x=700, y=180)
    y_int = b("Integrator", "y position", initial_condition=0.0, x=700, y=240)
    mux = b("Mux", "pose", inputs=4, x=840, y=210)
    sc = b("Scope", "Ground vehicle kinematics", x=980, y=210)
    m = model(8, 0.01,
              [vel, steer, wb, tan, prod1, gain_wb, yaw_rate, cos, sin, prod_x,
               prod_y, x_int, y_int, mux, sc],
              [connect(steer["id"], tan["id"]),
               connect(vel["id"], prod1["id"], dst_port=0),
               connect(tan["id"], prod1["id"], dst_port=1),
               connect(prod1["id"], gain_wb["id"]),
               connect(gain_wb["id"], yaw_rate["id"]),
               connect(yaw_rate["id"], cos["id"]),
               connect(yaw_rate["id"], sin["id"]),
               connect(vel["id"], prod_x["id"], dst_port=0),
               connect(cos["id"], prod_x["id"], dst_port=1),
               connect(vel["id"], prod_y["id"], dst_port=0),
               connect(sin["id"], prod_y["id"], dst_port=1),
               connect(prod_x["id"], x_int["id"]),
               connect(prod_y["id"], y_int["id"]),
               connect(x_int["id"], mux["id"], dst_port=0),
               connect(y_int["id"], mux["id"], dst_port=1),
               connect(yaw_rate["id"], mux["id"], dst_port=2),
               connect(gain_wb["id"], mux["id"], dst_port=3),
               connect(mux["id"], sc["id"])],
              "Kinematic ground vehicle: unicycle/bicycle pose integration.")
    write("robotics_ground_vehicle", m)


# ---------------------------------------------------------------------------
# 8. Manipulation forward kinematics (2-link arm)
#    x = L1*cos(t1) + L2*cos(t1+t2); y = L1*sin(t1) + L2*sin(t1+t2)
# ---------------------------------------------------------------------------
def manipulation_fk():
    b = block
    t1 = b("Constant", "theta1", value=0.5, y=0)
    t2 = b("Constant", "theta2", value=0.7, y=50)
    L1 = b("Constant", "link1", value=1.0, y=100)
    L2 = b("Constant", "link2", value=0.8, y=150)
    sum_t = b("Sum", "theta1+theta2", signs="++", x=140, y=25)
    c1 = b("Trig", "cos(t1)", operator="cos", x=140, y=0)
    s1 = b("Trig", "sin(t1)", operator="sin", x=140, y=50)
    c12 = b("Trig", "cos(t1+t2)", operator="cos", x=140, y=100)
    s12 = b("Trig", "sin(t1+t2)", operator="sin", x=140, y=150)
    x1 = b("Product", "L1*cos(t1)", ops="**", x=280, y=0)
    y1 = b("Product", "L1*sin(t1)", ops="**", x=280, y=50)
    x2 = b("Product", "L2*cos(t1+t2)", ops="**", x=280, y=100)
    y2 = b("Product", "L2*sin(t1+t2)", ops="**", x=280, y=150)
    x_ee = b("Sum", "x_ee", signs="++", x=420, y=25)
    y_ee = b("Sum", "y_ee", signs="++", x=420, y=125)
    mux = b("Mux", "end_effector", inputs=4, x=560, y=75)
    sc = b("Scope", "2-link forward kinematics", x=700, y=75)
    m = model(4, 0.01,
              [t1, t2, L1, L2, sum_t, c1, s1, c12, s12, x1, y1, x2, y2, x_ee,
               y_ee, mux, sc],
              [connect(t1["id"], sum_t["id"], dst_port=0),
               connect(t2["id"], sum_t["id"], dst_port=1),
               connect(t1["id"], c1["id"]),
               connect(t1["id"], s1["id"]),
               connect(sum_t["id"], c12["id"]),
               connect(sum_t["id"], s12["id"]),
               connect(L1["id"], x1["id"], dst_port=0),
               connect(c1["id"], x1["id"], dst_port=1),
               connect(L1["id"], y1["id"], dst_port=0),
               connect(s1["id"], y1["id"], dst_port=1),
               connect(L2["id"], x2["id"], dst_port=0),
               connect(c12["id"], x2["id"], dst_port=1),
               connect(L2["id"], y2["id"], dst_port=0),
               connect(s12["id"], y2["id"], dst_port=1),
               connect(x1["id"], x_ee["id"], dst_port=0),
               connect(x2["id"], x_ee["id"], dst_port=1),
               connect(y1["id"], y_ee["id"], dst_port=0),
               connect(y2["id"], y_ee["id"], dst_port=1),
               connect(t1["id"], mux["id"], dst_port=0),
               connect(t2["id"], mux["id"], dst_port=1),
               connect(x_ee["id"], mux["id"], dst_port=2),
               connect(y_ee["id"], mux["id"], dst_port=3),
               connect(mux["id"], sc["id"])],
              "2-link planar forward kinematics: end-effector (x,y) from joint "
              "angles and link lengths.")
    write("robotics_manipulation_fk", m)


# ---------------------------------------------------------------------------
# 9. Perception sensor conditioning (low-pass + washout/high-pass + clip)
# ---------------------------------------------------------------------------
def perception_conditioning():
    b = block
    raw = b("Constant", "raw_sensor", value=1.0, y=0)
    sens = b("Gain", "sensitivity 9.81", gain=9.81, x=140, y=0)
    lp = b("Transfer Fcn", "low-pass 1/(0.5s+1)", numerator="[1]",
           denominator="[0.5, 1]", x=280, y=0)
    hp = b("Transfer Fcn", "high-pass s/(0.5s+1)", numerator="[1, 0]",
           denominator="[0.5, 1]", x=280, y=100)
    clip = b("Saturation", "high-pass clip", lower_limit=-2.0, upper_limit=2.0,
             x=420, y=100)
    mux = b("Mux", "channels", inputs=4, x=560, y=40)
    sc = b("Scope", "Perception: raw / low-pass / high-pass / clipped", x=700,
           y=40)
    m = model(6, 0.01,
              [raw, sens, lp, hp, clip, mux, sc],
              [connect(raw["id"], sens["id"]),
               connect(sens["id"], lp["id"]),
               connect(sens["id"], hp["id"]),
               connect(hp["id"], clip["id"]),
               connect(raw["id"], mux["id"], dst_port=0),
               connect(lp["id"], mux["id"], dst_port=1),
               connect(hp["id"], mux["id"], dst_port=2),
               connect(clip["id"], mux["id"], dst_port=3),
               connect(mux["id"], sc["id"])],
              "Perception sensor conditioning: sensitivity scaling, low-pass "
              "and washout (high-pass) filtering with output clipping.")
    write("robotics_perception_conditioning", m)


# ---------------------------------------------------------------------------
# 10. Hardware connectivity: digital baud-rate counter + UART start-bit detect
#     (Unit Delay / Switch / Product / Sum — genuine digital hardware blocks).
# ---------------------------------------------------------------------------
def hardware_crc():
    b = block
    one = b("Constant", "one", value=1.0, y=0)
    div9 = b("Constant", "modulus_minus_one", value=9.0, y=40)
    zero = b("Constant", "zero", value=0.0, y=80)
    count = b("Unit Delay", "baud counter", sample_time=0.01,
              initial_condition=0.0, x=140, y=40)
    inc = b("Sum", "count+1", signs="++", x=140, y=0)
    div = b("Constant", "divisor 10", value=10.0, y=80)
    wrap = b("Switch", "wrap at divisor", threshold=10.0, x=280, y=40)
    diff = b("Sum", "count-9", signs="+-", x=280, y=0)
    tick = b("Switch", "tick at count==9", threshold=0.0, x=420, y=0)
    one_tick = b("Constant", "tick=1", value=1.0, y=0)
    zero_tick = b("Constant", "tick=0", value=0.0, y=40)
    serial = b("Step", "serial line (idle 1 -> start 0)", step_time=3.0,
               initial_val=1.0, final_val=0.0, x=140, y=160)
    prev = b("Unit Delay", "serial previous", sample_time=0.01,
             initial_condition=1.0, x=280, y=160)
    not_s = b("Sum", "1 - serial", signs="+-", x=280, y=200)
    start = b("Product", "start pulse", ops="**", x=420, y=160)
    mux = b("Mux", "debug", inputs=4, x=560, y=120)
    sc = b("Scope", "Hardware: baud tick + UART start-bit detect", x=700, y=120)
    blocks = [one, div9, zero, count, inc, div, wrap, diff, tick, one_tick,
              zero_tick, serial, prev, not_s, start, mux, sc]
    wires = [connect(count["id"], inc["id"], dst_port=0),
             connect(one["id"], inc["id"], dst_port=1),
             connect(inc["id"], wrap["id"], dst_port=2),
             connect(count["id"], wrap["id"], dst_port=0),
             connect(div["id"], wrap["id"], dst_port=1),
             connect(wrap["id"], count["id"]),
             connect(count["id"], diff["id"], dst_port=0),
             connect(div9["id"], diff["id"], dst_port=1),
             connect(diff["id"], tick["id"], dst_port=0),
             connect(one_tick["id"], tick["id"], dst_port=1),
             connect(zero_tick["id"], tick["id"], dst_port=2),
             connect(serial["id"], prev["id"]),
             connect(one["id"], not_s["id"], dst_port=0),
             connect(serial["id"], not_s["id"], dst_port=1),
             connect(prev["id"], start["id"], dst_port=0),
             connect(not_s["id"], start["id"], dst_port=1),
             connect(serial["id"], mux["id"], dst_port=0),
             connect(prev["id"], mux["id"], dst_port=1),
             connect(tick["id"], mux["id"], dst_port=2),
             connect(start["id"], mux["id"], dst_port=3),
             connect(mux["id"], sc["id"])]
    m = model(6, 0.01, blocks, wires,
              "Hardware connectivity: baud-rate counter (Unit Delay/Switch) "
              "plus UART falling-edge start-bit detection.")
    write("robotics_hardware_crc", m)


if __name__ == "__main__":
    path_following_stanley()
    multi_loop_pid()
    acc_adaptive_cruise()
    uav_mixer()
    marine_los()
    auv_3dof()
    ground_vehicle()
    manipulation_fk()
    perception_conditioning()
    hardware_crc()
    print(f"\nTotal models written: 10 -> {EXAMPLES}")
