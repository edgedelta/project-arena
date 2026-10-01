FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
COPY run.sh /usr/local/bin/thumbnailer
RUN chmod 0755 /usr/local/bin/thumbnailer
WORKDIR /app
ENTRYPOINT ["/usr/local/bin/thumbnailer"]
