"""Interactive iFogSim2 digital twin and fog/cloud placement comparison."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifogsim.runner import java_status, read_results, run_simulation
from ifogsim.sensor_readings import read_sensor_readings


st.set_page_config(page_title="iFogSim Digital Twin", page_icon="🛰️", layout="wide")
st.markdown(
    """
    <style>
      .hero { padding: 1.4rem 1.6rem; border-radius: 18px;
        background: linear-gradient(120deg,#0d2438 0%,#155e63 58%,#76b77a 125%);
        color: #f7fbff; margin-bottom: 1.2rem; }
      .hero-kicker { text-transform: uppercase; letter-spacing: .16em; font-size: .76rem;
        font-weight: 700; opacity: .82; }
      .hero h1 { margin: .35rem 0 .45rem 0; color: white; }
      .hero p { margin: 0; max-width: 860px; font-size: 1.02rem; opacity: .93; }
      .section-label { color: #2b7a70; font-size: .76rem; font-weight: 700;
        letter-spacing: .1em; text-transform: uppercase; }
    </style>
    <div class="hero">
      <div class="hero-kicker">AeroFog · Fog Computing Simulation</div>
      <h1>iFogSim Digital Twin</h1>
      <p>Compare simulated sensor-to-pump performance when control runs at the greenhouse fog gateway or in the cloud.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

status = java_status()
if not status["available"]:
    st.warning(
        "Java 21 or newer is required to run the iFogSim simulation.",
        icon="☕",
    )

left, right = st.columns([1.08, 1], gap="large")
with left:
    st.markdown('<div class="section-label">Topology</div>', unsafe_allow_html=True)
    st.graphviz_chart(
        """
        digraph aeroponics {
          graph [rankdir=LR, bgcolor="transparent", pad="0.24", nodesep="0.42", ranksep="0.55"];
          node [shape=box, style="rounded,filled", fontname="Arial", fontsize=11, margin="0.16,0.11", color="#d8e7e5"];
          edge [fontname="Arial", fontsize=9, color="#56827f", arrowsize=0.7];
          sensors [label="Humidity sensors\n1–16 greenhouse zones", fillcolor="#e4f4ed", fontcolor="#163a35"];
          edgeNode [label="Sensor / actuator nodes\n2 ms uplink", fillcolor="#eaf3fb", fontcolor="#1c3750"];
          gateway [label="Greenhouse fog gateway\nlocal control", fillcolor="#c9eee2", fontcolor="#123e37", penwidth=2];
          cloud [label="Remote cloud\nWAN delay adjustable", fillcolor="#e9e7fa", fontcolor="#342d58"];
          pump [label="Misting pump actuators\ncontrol-loop endpoint", fillcolor="#fff1d6", fontcolor="#594316"];
          sensors -> edgeNode [label="1 ms"];
          edgeNode -> gateway [label="2 ms"];
          gateway -> cloud [label="WAN"];
          gateway -> pump [label="Fog placement"];
          cloud -> pump [label="Cloud placement"];
        }
        """
    )
with right:
    st.markdown('<div class="section-label">Placement comparison</div>', unsafe_allow_html=True)
    st.markdown(
        "**Fog:** controller at the greenhouse gateway.  \n"
        "**Cloud:** controller in the remote cloud.  \n"
        "Compare loop latency and per-zone humidity readings below."
    )

st.divider()
st.subheader("Fog vs cloud simulation")

control_cols = st.columns([1, 1, 1, 1.15], gap="medium")
with control_cols[0]:
    sensor_count = st.slider("Greenhouse sensor zones", 1, 16, 3)
with control_cols[1]:
    wan_latency_ms = st.slider("Gateway → cloud delay (ms)", 20, 250, 100, step=10)
with control_cols[2]:
    simulation_seconds = st.select_slider("Simulation duration", options=[100, 200, 300, 600, 1000], value=300, format_func=lambda value: f"{value} s")
with control_cols[3]:
    run_clicked = st.button(
        "▶  Run fog + cloud comparison",
        type="primary",
        use_container_width=True,
        disabled=not status["available"],
    )

if run_clicked:
    try:
        with st.spinner("Building the simulator and running both placements…"):
            outcome = run_simulation(
                mode="both",
                sensor_count=sensor_count,
                wan_latency_ms=wan_latency_ms,
                simulation_seconds=simulation_seconds,
            )
        st.session_state["ifogsim_last_build"] = outcome["build"]
        st.success("Fog and cloud simulation complete.")
    except Exception as exc:  # Keep compiler/runtime diagnostics visible in the lab.
        st.error("The simulation did not finish. Use the message below to identify what needs fixing.")
        st.code(str(exc), language="text")

results = read_results()
if results:
    frame = pd.DataFrame(results)
    frame["avg_loop_latency_ms"] = pd.to_numeric(frame["avg_loop_latency_ms"], errors="coerce")
    frame["sensor_nodes"] = pd.to_numeric(frame["sensor_nodes"], errors="coerce").astype("Int64")
    frame["wan_latency_ms"] = pd.to_numeric(frame["wan_latency_ms"], errors="coerce")

    fog_row = next((row for row in results if row["scenario"] == "fog"), None)
    cloud_row = next((row for row in results if row["scenario"] == "cloud"), None)
    comparable_fields = ("sensor_nodes", "wan_latency_ms", "simulation_duration_s")
    same_experiment = bool(fog_row and cloud_row) and all(
        fog_row.get(field) == cloud_row.get(field) for field in comparable_fields
    )
    if same_experiment:
        try:
            fog_ms = float(fog_row["avg_loop_latency_ms"])
            cloud_ms = float(cloud_row["avg_loop_latency_ms"])
        except (TypeError, ValueError):
            st.warning("The latest run did not produce a completed sensor-to-pump loop sample. Increase simulated duration and run again.")
            fog_ms = cloud_ms = None
        if fog_ms is None or cloud_ms is None:
            pass
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Fog placement · mean loop", f"{fog_ms:.2f} ms")
            c2.metric("Cloud placement · mean loop", f"{cloud_ms:.2f} ms", delta=f"{cloud_ms - fog_ms:+.2f} ms vs fog", delta_color="inverse")
            c3.metric("Current sensor zones", f"{fog_row['sensor_nodes']}", help="Both results use the same sensor-zone count.")

            chart = go.Figure(
                go.Bar(
                    x=["Fog gateway", "Remote cloud"],
                    y=[fog_ms, cloud_ms],
                    marker_color=["#2a9d78", "#6876c5"],
                    text=[f"{fog_ms:.2f} ms", f"{cloud_ms:.2f} ms"],
                    textposition="outside",
                    cliponaxis=False,
                )
            )
            chart.update_layout(
                title="Humidity-to-pump application-loop latency",
                yaxis_title="Simulated latency (ms)",
                height=370,
                margin=dict(l=15, r=15, t=55, b=20),
                showlegend=False,
            )
            st.plotly_chart(chart, use_container_width=True)
    elif fog_row and cloud_row:
        st.warning("The latest fog and cloud results used different experiment settings; rerun the comparison to make an apples-to-apples chart.")
    else:
        st.info("Run both placement modes to produce a direct comparison.")

    sensor_readings = read_sensor_readings("fog")
    st.markdown("#### iFogSim humidity sensor readings")
    st.caption("Simulated humidity readings by sensor zone.")
    if sensor_readings:
        sensor_frame = pd.DataFrame(sensor_readings)
        sensor_frame["simulation_time_s"] = pd.to_numeric(sensor_frame["simulation_time_s"], errors="coerce")
        sensor_frame["humidity_pct"] = pd.to_numeric(sensor_frame["humidity_pct"], errors="coerce")
        latest_by_zone = (
            sensor_frame.sort_values("simulation_time_s")
            .groupby("sensor_zone", as_index=False)
            .tail(1)
            .sort_values("sensor_zone")
        )
        st.dataframe(
            latest_by_zone.rename(
                columns={
                    "sensor_zone": "Sensor zone",
                    "simulation_time_s": "Simulation time (s)",
                    "humidity_pct": "Humidity reading (%)",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

        sensor_chart = go.Figure()
        for zone, zone_frame in sensor_frame.groupby("sensor_zone"):
            sensor_chart.add_trace(
                go.Scatter(
                    x=zone_frame["simulation_time_s"],
                    y=zone_frame["humidity_pct"],
                    mode="lines+markers",
                    marker=dict(size=4),
                    name=zone,
                )
            )
        sensor_chart.update_layout(
            title="Simulated humidity readings by sensor zone",
            xaxis_title="Simulation time (s)",
            yaxis_title="Humidity (%)",
            height=330,
            margin=dict(l=15, r=15, t=50, b=20),
        )
        st.plotly_chart(sensor_chart, use_container_width=True)
        st.caption(f"{len(sensor_frame):,} readings recorded from {sensor_frame['sensor_zone'].nunique()} virtual zones in the fog run.")
        st.download_button(
            "Download iFogSim sensor readings (CSV)",
            data=sensor_frame.to_csv(index=False).encode("utf-8"),
            file_name="aeroponics_ifogsim_sensor_readings.csv",
            mime="text/csv",
        )
    else:
        st.info("Run the comparison to view per-zone humidity readings and latency results.")

    st.markdown("#### Run details")
    st.dataframe(
        frame.rename(
            columns={
                "scenario": "Placement",
                "controller_device": "Controller location",
                "sensor_nodes": "Sensor zones",
                "wan_latency_ms": "WAN link (ms)",
                "simulation_duration_s": "Simulated duration (s)",
                "avg_loop_latency_ms": "Mean loop latency (ms)",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.download_button(
        "Download these iFogSim results (CSV)",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="aeroponics_ifogsim_results.csv",
        mime="text/csv",
    )
else:
    st.info("Run the fog + cloud comparison to generate humidity readings and latency results.")

