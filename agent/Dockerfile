FROM python:3.13-slim

WORKDIR /opt/onesearch

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 onesearch \
    && useradd --uid 1000 --gid onesearch --create-home --shell /usr/sbin/nologin onesearch

COPY shared /opt/onesearch/shared
COPY backend /opt/onesearch/backend
COPY agent /opt/onesearch/agent

RUN pip install --no-cache-dir /opt/onesearch/shared /opt/onesearch/backend /opt/onesearch/agent

COPY agent/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /var/lib/onesearch-agent \
    && chown onesearch:onesearch /var/lib/onesearch-agent

ENV DOCKER_CONTAINER=1 \
    ONESEARCH_AGENT_CONFIG=/var/lib/onesearch-agent/config.toml \
    PUID=1000 \
    PGID=1000
VOLUME ["/var/lib/onesearch-agent"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["run"]
