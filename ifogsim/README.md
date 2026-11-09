# iFogSim2 Digital Twin

The aeroponics project now includes the official iFogSim2 source and bundled libraries under [`toolkit/`](toolkit/), alongside a custom Java model of the greenhouse control loop. The dashboard's **iFogSim Digital Twin** page can compile and run the model locally, compare fog and cloud placement, and display the generated measurements.

The upstream toolkit is maintained by [CLOUDS Lab](https://github.com/Cloudslab/iFogSim); its source license is included in [`toolkit/LICENSE.txt`](toolkit/LICENSE.txt). This integration uses iFogSim's CloudSim-based device, application-module, sensor, actuator, and application-loop APIs.

## Architecture represented

| iFogSim element | Project component | Model details |
| --- | --- | --- |
| Sensors | Humidity sensors in greenhouse zones | One reading every 2 simulated seconds |
| Edge devices | Sensor nodes and misting pumps | Sensor and actuator each add 1 ms local latency |
| Fog device | Greenhouse gateway | 2,000 MIPS; 2 ms uplink to each sensor node |
| Cloud device | Remote cloud | 40,000 MIPS; WAN delay configurable in the lab |
| Application module | `misting_controller` | Placed at the gateway for the fog run, cloud for the cloud run |
| Application loop | Humidity reading → controller → pump command | iFogSim reports the average simulated end-to-end loop delay |
| Cloud module | `telemetry_archive` | Stays in the cloud in both cases |

Both runs keep the same topology and traffic. The controller's location is the variable under study. Sensor-zone count and gateway-to-cloud link delay can be varied in the UI or command line.

## Run the complete project

1. Install Python and Java **JDK 21 or newer**. The bundled iFogSim2 CloudSim code uses Java 21 collection APIs. The simulator must be able to find both `java` and `javac` on `PATH`; setting `JAVA_HOME` to the JDK folder also works.
2. Open a terminal in the project folder and install the Python packages:

   ```text
   python -m pip install -r requirements.txt
   ```

3. Start the integrated Python system:

   ```text
   python run_all.py
   ```

4. Open `http://localhost:8501`, then select **iFogSim Digital Twin** from Streamlit's page navigation.
5. Set the number of sensor zones, WAN link delay, and simulated duration. Click **Run fog + cloud comparison**.
6. The first run compiles the included toolkit; later runs reuse the compiled classes. The page presents the real iFogSim loop delays and offers a CSV download.

The latest run is saved in `ifogsim/results/ifogsim_fog.csv` and `ifogsim/results/ifogsim_cloud.csv`. The compiled classes are local build output and are not committed to Git.

### Command-line run

From the project folder, run both placements with three sensor zones, a 100 ms gateway-to-cloud delay, and 300 simulated seconds:

```text
python ifogsim/runner.py --mode both --sensors 3 --wan-ms 100 --seconds 300
```

To run one placement, replace `both` with `fog` or `cloud`. Supported ranges are 1–16 sensor zones, 1–1000 ms WAN delay, and 30–3600 simulated seconds.

## What to say in your presentation

“The Python application demonstrates the live MQTT sensor feed, local misting control, fault detection, and operator dashboard. I integrated iFogSim2 as a discrete-event digital twin of the same aeroponics architecture. The Java simulation models the sensor, edge nodes, fog gateway, cloud, control module, and pump actuator. I compare the average sensor-to-pump application-loop delay when the controller is placed at the greenhouse gateway versus in the cloud, holding the workload and topology constant. The dashboard also lets me vary the sensor-zone count and WAN delay. iFogSim results are simulated measurements, while the Python demo's configurable cloud delay is a separate illustration.”

## Interpretation and limitations

- The WAN delay is a user-selected simulation parameter, not a measurement of the actual internet connection.
- Simulated loop latency is not a physical pump switching time and does not establish plant-safety performance.
- The Python MQTT demo and iFogSim model are connected through the shared project and dashboard, but the Java model simulates workload/topology independently of live MQTT messages.
- The Streamlit Community Cloud host may not include a Java JDK. Use the local project on the laptop for real iFogSim runs; the UI explains when the JDK is unavailable.

