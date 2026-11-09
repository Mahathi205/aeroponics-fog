package org.fog.test.perfeval;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;

import org.cloudbus.cloudsim.Host;
import org.cloudbus.cloudsim.Log;
import org.cloudbus.cloudsim.Pe;
import org.cloudbus.cloudsim.Storage;
import org.cloudbus.cloudsim.core.CloudSim;
import org.cloudbus.cloudsim.power.PowerHost;
import org.cloudbus.cloudsim.provisioners.RamProvisionerSimple;
import org.cloudbus.cloudsim.sdn.overbooking.BwProvisionerOverbooking;
import org.cloudbus.cloudsim.sdn.overbooking.PeProvisionerOverbooking;
import org.fog.application.AppEdge;
import org.fog.application.AppLoop;
import org.fog.application.Application;
import org.fog.application.selectivity.FractionalSelectivity;
import org.fog.entities.Actuator;
import org.fog.entities.FogBroker;
import org.fog.entities.FogDevice;
import org.fog.entities.FogDeviceCharacteristics;
import org.fog.entities.Sensor;
import org.fog.entities.Tuple;
import org.fog.placement.Controller;
import org.fog.placement.ModuleMapping;
import org.fog.placement.ModulePlacementEdgewards;
import org.fog.policy.AppModuleAllocationPolicy;
import org.fog.scheduler.StreamOperatorScheduler;
import org.fog.utils.Config;
import org.fog.utils.FogLinearPowerModel;
import org.fog.utils.FogEvents;
import org.fog.utils.FogUtils;
import org.fog.utils.TimeKeeper;
import org.fog.utils.distribution.DeterministicDistribution;

/**
 * Small iFogSim model of the aeroponics humidity-to-misting control loop.
 * Run once with "fog" and once with "cloud" to compare module placement.
 */
public class AeroponicsFogSimulation {
    private static final String APP_ID = "aeroponics";
    private static final String CONTROLLER = "misting_controller";
    private static final String ARCHIVE = "telemetry_archive";
    private static final String GATEWAY = "greenhouse_gateway";
    private static final String SENSOR_TYPE = "HUMIDITY_READING";
    private static final String ACTUATOR_TYPE = "MISTING_PUMP";

    private static final List<FogDevice> DEVICES = new ArrayList<FogDevice>();
    private static final List<Sensor> SENSORS = new ArrayList<Sensor>();
    private static final List<Actuator> ACTUATORS = new ArrayList<Actuator>();
    private static String currentMode;
    private static int sensorReadingsEmitted;

    private AeroponicsFogSimulation() { }

    public static void main(String[] args) throws Exception {
        String mode = args.length == 0 ? "fog" : args[0].trim().toLowerCase();
        int sensorCount = args.length > 1 ? Integer.parseInt(args[1]) : 3;
        double wanLatencyMs = args.length > 2 ? Double.parseDouble(args[2]) : 100.0;
        int simulationSeconds = args.length > 3 ? Integer.parseInt(args[3]) : 300;
        if (!mode.equals("fog") && !mode.equals("cloud")) {
            throw new IllegalArgumentException(
                    "Usage: AeroponicsFogSimulation [fog|cloud] [sensor-count] [wan-ms] [duration-seconds]");
        }
        if (sensorCount < 1 || sensorCount > 16 || wanLatencyMs < 1 || simulationSeconds < 30) {
            throw new IllegalArgumentException("Use 1-16 sensors, WAN latency >= 1 ms, duration >= 30 s");
        }

        currentMode = mode;
        sensorReadingsEmitted = 0;
        resetSensorReadings(mode);
        Log.disable();
        Config.MAX_SIMULATION_TIME = simulationSeconds;
        CloudSim.init(1, Calendar.getInstance(), false);

        FogBroker broker = new FogBroker("aeroponics-broker");
        Application application = createApplication(broker.getId());
        application.setUserId(broker.getId());
        createTopology(broker.getId(), sensorCount, wanLatencyMs);

        ModuleMapping mapping = ModuleMapping.createModuleMapping();
        mapping.addModuleToDevice(CONTROLLER, mode.equals("fog") ? GATEWAY : "cloud");
        mapping.addModuleToDevice(ARCHIVE, "cloud");

        Controller controller = new ResultController("aeroponics-controller", DEVICES,
                SENSORS, ACTUATORS, mode, sensorCount, wanLatencyMs, simulationSeconds);
        controller.submitApplication(application,
                new ModulePlacementEdgewards(DEVICES, SENSORS, ACTUATORS, application, mapping));

        TimeKeeper.getInstance().setSimulationStartTime(Calendar.getInstance().getTimeInMillis());
        CloudSim.startSimulation();
    }

    private static Application createApplication(int userId) {
        Application app = Application.createApplication(APP_ID, userId);
        app.addAppModule(CONTROLLER, 10);
        app.addAppModule(ARCHIVE, 10);

        // Edge lengths are bytes; CPU lengths are millions of instructions (MI).
        app.addAppEdge(SENSOR_TYPE, CONTROLLER, 1000, 500, SENSOR_TYPE, Tuple.UP, AppEdge.SENSOR);
        app.addAppEdge(CONTROLLER, ACTUATOR_TYPE, 100, 100, "MIST_COMMAND", Tuple.DOWN, AppEdge.ACTUATOR);
        app.addAppEdge(CONTROLLER, ARCHIVE, 500, 300, "CONTROL_LOG", Tuple.UP, AppEdge.MODULE);

        app.addTupleMapping(CONTROLLER, SENSOR_TYPE, "MIST_COMMAND", new FractionalSelectivity(1.0));
        app.addTupleMapping(CONTROLLER, SENSOR_TYPE, "CONTROL_LOG", new FractionalSelectivity(1.0));
        app.setLoops(java.util.Collections.singletonList(new AppLoop(
                java.util.Arrays.asList(SENSOR_TYPE, CONTROLLER, ACTUATOR_TYPE))));
        return app;
    }

    private static void createTopology(int userId, int sensorCount, double wanLatencyMs) throws Exception {
        FogDevice cloud = createFogDevice("cloud", 40000, 32768, 10000, 10000,
                0, 0.01, 100, 80);
        cloud.setParentId(-1);
        DEVICES.add(cloud);

        FogDevice gateway = createFogDevice(GATEWAY, 2000, 4096, 10000, 10000,
                1, 0.0, 80, 50);
        gateway.setParentId(cloud.getId());
        gateway.setUplinkLatency(wanLatencyMs); // WAN round trip is intentionally visible in cloud mode.
        DEVICES.add(gateway);

        for (int i = 1; i <= sensorCount; i++) {
            String zone = String.format("%02d", i);
            FogDevice sensorNode = createFogDevice("sensor_node_" + zone, 500, 1024,
                    10000, 10000, 2, 0.0, 40, 20);
            sensorNode.setParentId(gateway.getId());
            sensorNode.setUplinkLatency(2);
            DEVICES.add(sensorNode);

            Sensor humidity = new TelemetrySensor("chamber_humidity_" + zone, SENSOR_TYPE,
                    userId, APP_ID, new DeterministicDistribution(2.0), i);
            humidity.setGatewayDeviceId(sensorNode.getId());
            humidity.setLatency(1.0);
            SENSORS.add(humidity);

            Actuator pump = new Actuator("misting_pump_" + zone, userId, APP_ID, ACTUATOR_TYPE);
            pump.setGatewayDeviceId(sensorNode.getId());
            pump.setLatency(1.0);
            ACTUATORS.add(pump);
        }
    }

    private static FogDevice createFogDevice(String name, long mips, int ram,
            long uplinkBandwidth, long downlinkBandwidth, int level,
            double ratePerMips, double busyPower, double idlePower) throws Exception {
        List<Pe> peList = new ArrayList<Pe>();
        peList.add(new Pe(0, new PeProvisionerOverbooking(mips)));
        int hostId = FogUtils.generateEntityId();
        PowerHost host = new PowerHost(hostId, new RamProvisionerSimple(ram),
                new BwProvisionerOverbooking(10000), 1000000, peList,
                new StreamOperatorScheduler(peList), new FogLinearPowerModel(busyPower, idlePower));
        List<Host> hosts = new ArrayList<Host>();
        hosts.add(host);

        FogDeviceCharacteristics characteristics = new FogDeviceCharacteristics(
                "x86", "Linux", "Xen", host, 10.0, 3.0, 0.05, 0.001, 0.0);
        FogDevice device = new FogDevice(name, characteristics,
                new AppModuleAllocationPolicy(hosts), new LinkedList<Storage>(),
                10, uplinkBandwidth, downlinkBandwidth, 0, ratePerMips);
        device.setLevel(level);
        return device;
    }

    private static void writeResult(String mode, int sensorCount, double wanLatencyMs,
            int simulationSeconds, Double meanLatency) throws IOException {
        Path results = resultsDirectory();
        Files.createDirectories(results);
        String latency = meanLatency == null ? "" : meanLatency.toString();
        String csv = "scenario,controller_device,sensor_nodes,wan_latency_ms,simulation_duration_s,avg_loop_latency_ms\n"
                + mode + "," + (mode.equals("fog") ? GATEWAY : "cloud") + ","
                + sensorCount + "," + wanLatencyMs + "," + simulationSeconds + "," + latency + "\n";
        Files.write(results.resolve("ifogsim_" + mode + ".csv"),
                csv.getBytes(StandardCharsets.UTF_8));
    }

    private static Path resultsDirectory() {
        return Paths.get(System.getProperty("aeroponics.resultsDir", "ifogsim/results"));
    }

    private static Path sensorReadingsFile(String mode) {
        return resultsDirectory().resolve("ifogsim_sensor_readings_" + mode + ".csv");
    }

    private static void resetSensorReadings(String mode) throws IOException {
        Path results = resultsDirectory();
        Files.createDirectories(results);
        Path readings = sensorReadingsFile(mode);
        Files.deleteIfExists(readings);
        Files.write(readings,
                "scenario,sensor_zone,simulation_time_s,humidity_pct\n".getBytes(StandardCharsets.UTF_8),
                StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

    private static void recordHumidityReading(String sensorZone, int zoneIndex, double simulationTime) {
        // A repeatable virtual humidity signal lets the same sensor workload be
        // compared in the fog and cloud placements without claiming physical data.
        double humidity = 72.0 + 8.0 * Math.sin(simulationTime / 18.0 + (zoneIndex - 1) * 0.65);
        humidity = Math.max(40.0, Math.min(98.0, humidity));
        String row = String.format(java.util.Locale.ROOT, "%s,%s,%.2f,%.2f%n",
                currentMode, sensorZone, simulationTime, humidity);
        try {
            Files.write(sensorReadingsFile(currentMode), row.getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            sensorReadingsEmitted++;
        } catch (IOException e) {
            System.err.println("Could not save virtual sensor reading: " + e.getMessage());
        }
    }

    /** iFogSim sensor that records a numeric humidity sample each time it emits its tuple. */
    private static final class TelemetrySensor extends Sensor {
        private final String zoneName;
        private final int zoneIndex;

        TelemetrySensor(String name, String tupleType, int userId, String appId,
                DeterministicDistribution distribution, int zoneIndex) {
            super(name, tupleType, userId, appId, distribution);
            this.zoneName = "zone_" + String.format(java.util.Locale.ROOT, "%02d", zoneIndex);
            this.zoneIndex = zoneIndex;
        }

        @Override
        public void transmit() {
            recordHumidityReading(zoneName, zoneIndex, CloudSim.clock());
            super.transmit();
        }
    }

    /**
     * iFogSim's base Controller exits the JVM when its stop event is handled.
     * Save the metric before delegating that event to the base implementation.
     */
    private static final class ResultController extends Controller {
        private final String mode;
        private final int sensorCount;
        private final double wanLatencyMs;
        private final int simulationSeconds;

        ResultController(String name, List<FogDevice> devices, List<Sensor> sensors,
                List<Actuator> actuators, String mode, int sensorCount,
                double wanLatencyMs, int simulationSeconds) {
            super(name, devices, sensors, actuators);
            this.mode = mode;
            this.sensorCount = sensorCount;
            this.wanLatencyMs = wanLatencyMs;
            this.simulationSeconds = simulationSeconds;
        }

        @Override
        public void processEvent(org.cloudbus.cloudsim.core.SimEvent event) {
            if (event.getTag() == FogEvents.STOP_SIMULATION) {
                Map<Integer, Double> averages = TimeKeeper.getInstance().getLoopIdToCurrentAverage();
                Double meanLatency = averages.isEmpty() ? null : averages.values().iterator().next();
                System.out.println("Scenario: " + mode.toUpperCase());
                System.out.println("Placement: " + CONTROLLER + " on "
                        + (mode.equals("fog") ? GATEWAY : "cloud"));
                System.out.println("Sensor zones / WAN latency: " + sensorCount + " / " + wanLatencyMs + " ms");
                System.out.println("Virtual humidity readings emitted: " + sensorReadingsEmitted);
                System.out.println("Humidity-to-pump average loop latency (ms): "
                        + (meanLatency == null ? "no completed loop samples" : meanLatency));
                try {
                    writeResult(mode, sensorCount, wanLatencyMs, simulationSeconds, meanLatency);
                } catch (IOException e) {
                    System.err.println("Could not write iFogSim result CSV: " + e.getMessage());
                }
            }
            super.processEvent(event);
        }
    }
}
