FROM redis:7-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499
COPY run.sh /usr/local/bin/cache-warmer
RUN chmod 0755 /usr/local/bin/cache-warmer
WORKDIR /app
ENTRYPOINT ["/usr/local/bin/cache-warmer"]
