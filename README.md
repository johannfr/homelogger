# homelogger

This is a service that logs a bunch of MQTT-topics to InfluxDB.

Those are the topic-prefices that match my own installation and will not work with the Shelly defaults.

## Installation

I installed this in `/opt` but this can be anywhere. Just update the homelogger.service file to match.

```bash
cd /opt
git clone http://github.com/johannfr/homelogger
cd homelogger
python -m venv venv
```

Activate the venv
```bash
source venv/bin/activate
```

And install everything

```bash
pip3 install .
```

Then copy the homelogger.service file to /lib/systemd/system (or another systemd directory of your liking), update necessary environment variables, enable it and run it.

```bash
cp homelogger.service /lib/systemd/system
systemctl enable homelogger
systemctl start homelogger
```
