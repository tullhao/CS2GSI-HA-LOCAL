FROM ghcr.io/home-assistant/base:latest

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY app /app/app
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
