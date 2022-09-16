from rich.traceback import install as traceback_install
from rich.logging import RichHandler
import click
import paho.mqtt.client as mqtt
import pendulum
from influxdb import InfluxDBClient
import logging, sys, json, threading
from time import sleep

if sys.stdin.isatty():
    traceback_install(show_locals=True)
    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])
else:
    logging.basicConfig(level=logging.INFO)

LOG = logging.getLogger("homelogger")
LOG.setLevel(logging.DEBUG)


def on_mqtt_connect(client, userdata, flags, rc):
    influx_client, cache = userdata
    mqtt_socket = client.socket()
    remote_host = mqtt_socket.getpeername()[0]
    remote_port = mqtt_socket.getpeername()[1]
    LOG.info(f"Connected to MQTT-broker: [{remote_host}]:[{remote_port}]")

    client.subscribe("shellies/lights/+/+/relay/+")
    client.subscribe("shellies/lights/+/+/light/+")
    client.subscribe("shellies/utils/+/relay/+")
    client.subscribe("shellies/+/+/sensor/+")
    client.subscribe("shellies/motion/+/status")
    client.subscribe("shellies/trv/+/status")


def on_mqtt_message(client, userdata, msg):
    influx_client, cache = userdata
    try:
        payload = int(msg.payload.decode("utf-8"))
    except ValueError:
        try:
            payload = float(msg.payload.decode("utf-8"))
        except ValueError:
            payload = msg.payload.decode("utf-8")

    topic_fields = msg.topic.split("/")
    LOG.debug(f"{msg.topic}: {msg.payload.decode('utf-8')}")
    if topic_fields[-2] in ["relay", "light"]:
        relevant_fields = [topic_fields[-4], topic_fields[-3], topic_fields[-1]]
        measurement_fields = {"value": payload}
    elif topic_fields[1] in ["dw", "ht"]:
        relevant_fields = [topic_fields[1], topic_fields[-3], topic_fields[-1]]
        measurement_fields = {"value": payload}
    elif topic_fields[1] == "motion":
        relevant_fields = [topic_fields[1], topic_fields[2]]
        measurement_fields = json.loads(payload)
        LOG.debug("Motion payload:")
        LOG.debug(measurement_fields)
    elif topic_fields[1] == "trv":
        relevant_fields = [topic_fields[1], topic_fields[2]]
        trv_status = json.loads(payload)
        measurement_fields = {
            "temperature": trv_status["tmp"]["value"],
            "setpoint": trv_status["target_t"]["value"],
            "bat": trv_status["bat"],
        }
        LOG.debug("TRV payload:")
        LOG.debug(measurement_fields)
    else:
        LOG.error(f"Unable to process topic: {msg.topic}")

    measurement_name = relevant_fields[0] + "".join(
        [f.title() for f in relevant_fields[1:]]
    )

    LOG.debug(f"{msg.topic}: {measurement_name}")
    measurement_data = [{"measurement": measurement_name, "fields": measurement_fields}]
    cache[msg.topic] = (pendulum.now(), measurement_data)
    try:
        influx_client.write_points(measurement_data)
    except Exception as e:
        LOG.error(f"Unable to write value: {e}")


def periodic_inject_from_cache(mqtt_client, influx_client, cache):
    while True:
        for topic in cache.keys():
            timestamp, measurement_data = cache[topic]
            if pendulum.now() >= timestamp.add(minutes=1):
                LOG.debug(f"Inject from cache: {topic}")
                try:
                    influx_client.write_points(measurement_data)
                except Exception as e:
                    LOG.error(f"Unable to write cached value: {e})")
                cache[topic] = (pendulum.now(), measurement_data)
        sleep(1)


# This envvars business is a bit of a mess, but auto_envvars_prefix wasn't working
# because of a mismatch between dashes and underscores and systemd not liking dashes
# in Environment definitions.
@click.command()
@click.option("--mqtt-hostname", default="localhost", envvar="HOMELOGGER_MQTT_HOSTNAME")
@click.option("--mqtt-port", default=1883, envvar="HOMELOGGER_MQTT_PORT")
@click.option("--mqtt-keepalive", default=60, envvar="HOMELOGGER_MQTT_KEEPALIVE")
@click.option("--mqtt-username", default=None, envvar="HOMELOGGER_MQTT_USERNAME")
@click.option("--mqtt-password", default=None, envvar="HOMELOGGER_MQTT_PASSWORD")
@click.option(
    "--influx-hostname", default="localhost", envvar="HOMELOGGER_INFLUX_HOSTNAME"
)
@click.option("--influx-port", default=8086, envvar="HOMELOGGER_INFLUX_PORT")
@click.option("--influx-username", default=None, envvar="HOMELOGGER_INFLUX_USERNAME")
@click.option("--influx-password", default=None, envvar="HOMELOGGER_INFLUX_PASSWORD")
@click.option(
    "--influx-database", default="homelogger", envvar="HOMELOGGER_INFLUX_DATABASE"
)
def main(
    mqtt_hostname,
    mqtt_port,
    mqtt_keepalive,
    mqtt_username,
    mqtt_password,
    influx_hostname,
    influx_port,
    influx_username,
    influx_password,
    influx_database,
):

    cache = {}

    influx_client = InfluxDBClient(
        host=influx_hostname,
        port=influx_port,
        username=influx_username,
        password=influx_password,
    )
    influx_client.create_database(influx_database)
    influx_client.switch_database(influx_database)

    mqtt_client = mqtt.Client(userdata=(influx_client, cache))
    mqtt_client.on_connect = on_mqtt_connect
    if mqtt_username and mqtt_password:
        mqtt_client.username_pw_set(mqtt_username, mqtt_password)
    mqtt_client.on_message = on_mqtt_message
    mqtt_client.connect(mqtt_hostname, mqtt_port, mqtt_keepalive)

    periodic = threading.Thread(
        target=periodic_inject_from_cache, args=(mqtt_client, influx_client, cache)
    )
    periodic.setDaemon(True)
    periodic.start()

    mqtt_client.loop_forever()


if __name__ == "__main__":
    main()
