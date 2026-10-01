FROM postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
COPY run.sh /usr/local/bin/catalog-maintenance
RUN chmod 0755 /usr/local/bin/catalog-maintenance
WORKDIR /app
ENTRYPOINT ["/usr/local/bin/catalog-maintenance"]
