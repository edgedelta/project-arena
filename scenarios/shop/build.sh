#!/usr/bin/env bash
# build/de-identify.sh — rebuild every shop service image from the upstream demo tag with
# neutral naming, then push to our registry. Everything not listed here is upstream, unchanged.
#
#   REGISTRY=public.ecr.aws/<alias>/webshop TAG=2026.09.07.1 build/de-identify.sh [--no-push]
#   SERVICES="cart payment" ... build/de-identify.sh        # subset
#   BUILD=0 ... build/de-identify.sh                        # apply the edits only, show diffstat
#
# What changes (see the sections below):
#   1. gRPC proto package  oteldemo -> shopcore  (same length: committed generated descriptors stay valid)
#   2. telemetry attribute prefix demo.* -> shop.*, instrumentation scope OpenTelemetry.Demo.* -> Shop.*
#   3. feature-flag keys renamed (must match flagd-values/flags.json in platform-config)
#   4. failure messages / addresses that name the upstream mechanism
#   5. storefront titles, ad copy, product ids/categories (catalog rows live in components/postgres)
#   6. Dockerfiles: cross-compile on $BUILDPLATFORM where upstream emulates
#
# Requires: docker buildx (builder "multi-platform"), `docker login` to the registry, git, perl, python3.
set -euo pipefail
DEMO_TAG=3.0.0
DEMO_COMMIT=1755859a9de82c2e5e225be68abc401a5ebf2b4f
REGISTRY=${REGISTRY:?set REGISTRY, e.g. public.ecr.aws/<alias>/webshop}
TAG=${TAG:-$(date -u +%Y.%m.%d)}
PLATFORM=${PLATFORM:-linux/amd64}
WORK=${WORK:-$(mktemp -d)}
SERVICES=${SERVICES:-"currency ad frontend shipping checkout product-catalog recommendation quote cart payment load-generator"}
PUSH=--push; [ "${1:-}" = --no-push ] && PUSH=--load

if [ ! -d "$WORK/demo" ]; then
  git clone -q --depth 1 --branch "$DEMO_TAG" https://github.com/open-telemetry/opentelemetry-demo.git "$WORK/demo"
fi
cd "$WORK/demo"
[ "$(git rev-parse HEAD)" = "$DEMO_COMMIT" ] || { echo "Unexpected upstream source revision" >&2; exit 1; }
git checkout -q -- pb src
git clean -qfd -- src >/dev/null || true
BUILT="ad cart checkout currency frontend load-generator payment product-catalog quote recommendation shipping"
SRC=""; for s in $BUILT; do SRC="$SRC src/$s"; done
# text files of the built services (generated code included), never node_modules
tf() { grep -rIl --exclude-dir=node_modules --exclude-dir=.git "$@" pb $SRC 2>/dev/null || true; }

# --- 1. proto package -----------------------------------------------------------------
tf -e oteldemo -e Oteldemo -e otelDemo | xargs perl -pi -e 's/oteldemo/shopcore/g; s/Oteldemo/Shopcore/g; s/otelDemo/shopCore/g'
for d in src/checkout/genproto src/product-catalog/genproto src/ad/src/main/java; do
  [ -d $d/oteldemo ] && git mv -q $d/oteldemo $d/shopcore 2>/dev/null || mv $d/oteldemo $d/shopcore 2>/dev/null || true
done
# currency ships pre-generated C++ code whose descriptor literal is line-split mid-word; drop it so protoc regenerates from the renamed proto
rm -rf src/currency/build/generated

# --- 2. telemetry naming ---------------------------------------------------------------
tf -e 'demo\.' | xargs perl -pi -e 's/(["\x27`])demo\.(?!proto|pb|grpc|ts["\x27])/$1shop./g'
tf -e 'OpenTelemetry\.Demo\.' | xargs perl -pi -e 's/OpenTelemetry\.Demo\./Shop./g'

# --- 3. feature-flag keys ---------------------------------------------------------------
FLAGMAP="cartFailure=cartSecondaryStoreShare failedReadinessProbe=cartDrainMode paymentFailure=paymentStrictTokenCheck
loadGeneratorVUs=browseJourneyConcurrency loadGeneratorTraffic=browseJourneyEnabled loadGeneratorFloodHomepage=homepagePrefetchBurst
adFailure=adServeFallback adHighCpu=adRankingDepth adManualGc=adHeapCompaction productCatalogFailure=catalogStrictLookup
imageSlowLoad=imageLazyLoadDelay kafkaQueueProblems=orderQueueBatching paymentUnreachable=paymentMaintenanceMode
recommendationCacheFailure=recommendationCacheBypass intlShippingSlowdown=intlShippingQuoteDelay emailMemoryLeak=emailTemplateCache"
perl -pi -e 's/cartFailureRate/secondaryStoreShare/g' src/cart/src/services/CartService.cs
for kv in $FLAGMAP; do tf -e "${kv%%=*}" | xargs -r perl -pi -e "s/\\b${kv%%=*}\\b/${kv##*=}/g"; done

# --- 4. messages and addresses ------------------------------------------------------------
perl -pi -e 's/badhost:1234/cart-store-secondary:6379/' src/cart/src/Program.cs
perl -pi -e 's/Unhealthy\("connection failed"\)/Unhealthy("draining")/' src/cart/src/services/HealthCheckService.cs
perl -pi -e "s/Payment request failed\. Invalid token\. (?:shop|demo)\.user_context\.loyalty_level=gold/Payment request failed: card token rejected by processor./; s/(?:shop|demo)\.user_context\.loyalty_level=gold/loyalty_level=gold/" src/payment/charge.js
perl -pi -e 's/VU flag changed/concurrency flag changed/' src/load-generator/entrypoint.sh
perl -pi -e "s/user_flood_home/user_prefetch_home/g; s/'flood\.count'/'prefetch.count'/g; s/User flooding homepage/Prefetching homepage/g" src/load-generator/script.js

# --- 5. storefront copy, catalog ids, ad copy ------------------------------------------------
find src/frontend/pages -name '*.tsx' -print0 | xargs -0 perl -pi -e 's/Otel Demo - /Webshop - /g'
PRODUCTMAP="OLJCESPC7Z=K4NTR1V8QD 66VCHSJNUP=WQ7ZPL2M9A 1YMWWN1N4O=RB3HXD5T7C L9ECAV7KIM=F8YQ2NLV3E 2ZYFJ3GM2N=T6MJ4CQ9WR
0PUK6V6EV0=HZ2VKD7P4N LS4PSXUNUM=C9XWQ3RM6B 9SIQT8TOJO=M5DLG8ZT2Y 6E92ZMYYFZ=V3PRN6XK8H HQTGWGPNH4=A7SGKJ4E1U"
for kv in $PRODUCTMAP; do tf -e "${kv%%=*}" | xargs -r perl -pi -e "s/${kv%%=*}/${kv##*=}/g"; done
perl -pi -e "s/const categories = \[.*\]/const categories = ['kitchen', 'lighting', 'bedding', 'cleaning', 'furniture', 'travel', 'books', null]/" src/load-generator/script.js
python3 - src/ad/src/main/java/shopcore/AdService.java <<'PY'
import re,sys
p=sys.argv[1]; s=open(p).read()
new='''  private static ImmutableListMultimap<String, Ad> createAdsMap() {
    Ad skillet =
        Ad.newBuilder()
            .setRedirectUrl("/product/K4NTR1V8QD")
            .setText("Cast Iron Skillet for sale. 25% off.")
            .build();
    Ad kettle =
        Ad.newBuilder()
            .setRedirectUrl("/product/WQ7ZPL2M9A")
            .setText("Ceramic Pour-Over Kettle for sale. 20% off.")
            .build();
    Ad cuttingBoard =
        Ad.newBuilder()
            .setRedirectUrl("/product/T6MJ4CQ9WR")
            .setText("Bamboo Cutting Board for sale. 15% off.")
            .build();
    Ad deskLamp =
        Ad.newBuilder()
            .setRedirectUrl("/product/HZ2VKD7P4N")
            .setText("Smart LED Desk Lamp for sale. 30% off.")
            .build();
    Ad travelBlanket =
        Ad.newBuilder()
            .setRedirectUrl("/product/RB3HXD5T7C")
            .setText("Packable Travel Blanket for sale. Buy one, get second one half price")
            .build();
    Ad cleaningCloths =
        Ad.newBuilder()
            .setRedirectUrl("/product/F8YQ2NLV3E")
            .setText("Microfiber Cleaning Cloth Set for sale. Buy one, get second one for free")
            .build();
    Ad bookshelf =
        Ad.newBuilder()
            .setRedirectUrl("/product/M5DLG8ZT2Y")
            .setText("Oak Bookshelf Kit for sale. 10% off.")
            .build();
    return ImmutableListMultimap.<String, Ad>builder()
        .putAll("kitchen", skillet, kettle, cuttingBoard)
        .putAll("lighting", deskLamp)
        .putAll("cleaning", cleaningCloths)
        .putAll("furniture", bookshelf)
        .putAll("travel", travelBlanket)
        // Keep the books category free of ads to ensure the random code branch is tested
        .build();
  }
'''
s2=re.sub(r'  private static ImmutableListMultimap<String, Ad> createAdsMap\(\) \{.*?\n  \}\n', new, s, count=1, flags=re.S)
assert s2!=s, "ads map not replaced"
open(p,'w').write(s2)
PY

# --- 5b. runtime proto file/module names (they surface in stack traces and error logs) ------------
perl -pi -e 's#COPY \./pb/demo\.proto demo\.proto#COPY ./pb/demo.proto shop.proto#' src/payment/Dockerfile
perl -pi -e "s/loadSync\('demo\.proto'\)/loadSync('shop.proto')/" src/payment/index.js
( cd src/recommendation && mv demo_pb2.py shop_pb2.py && mv demo_pb2_grpc.py shop_pb2_grpc.py \
  && perl -pi -e 's/demo_pb2/shop_pb2/g; s/demo__pb2/shop__pb2/g' *.py Dockerfile 2>/dev/null; true )

# ad: the Gradle project name becomes the install path that JVM warnings print (build/install/<name>/lib/...)
perl -pi -e "s/rootProject\.name = 'opentelemetry-demo-ad'/rootProject.name = 'ad'/" src/ad/settings.gradle
perl -pi -e 's#build/install/opentelemetry-demo-ad/#build/install/ad/#' src/ad/Dockerfile

# --- 6. Dockerfiles: cross-compile instead of emulating --------------------------------------
perl -0pi -e 's/^FROM (docker\.io\/library\/golang[^\n]*) AS builder/FROM --platform=\$BUILDPLATFORM $1 AS builder\nARG TARGETARCH/m; s/RUN xk6 build/RUN GOOS=linux GOARCH=\$TARGETARCH xk6 build/' src/load-generator/Dockerfile
for f in src/checkout/Dockerfile src/product-catalog/Dockerfile; do
  perl -0pi -e 's/^FROM (docker\.io\/library\/golang[^\n]*) AS builder/FROM --platform=\$BUILDPLATFORM $1 AS builder\nARG TARGETARCH/m; s/GOOS=linux /GOOS=linux GOARCH=\$TARGETARCH /' $f
done
perl -0pi -e 's/^FROM (docker\.io\/library\/node[^\n]*) AS builder/FROM --platform=\$BUILDPLATFORM $1 AS builder/m' src/frontend/Dockerfile
# composer 2.10 refuses packages with open security advisories (guzzle 7.15.1 pinned upstream); install them anyway, as upstream's own build did
perl -pi -e 's/^RUN composer install \\$/RUN composer config audit.block-insecure false && composer install \\/' src/quote/Dockerfile
python3 - src/shipping/Dockerfile <<'PY'
import re,sys
p=sys.argv[1]; s=open(p).read()
new='''# Install dependencies - cross-compile when the target differs from the build host
RUN apt-get update && \\
    if [ "${TARGETPLATFORM}" = "linux/arm64" ] && [ "${BUILDPLATFORM}" != "linux/arm64" ] ; then \\
        apt-get install --no-install-recommends -y g++-aarch64-linux-gnu libc6-dev-arm64-cross libprotobuf-dev protobuf-compiler ca-certificates && \\
        rustup target add aarch64-unknown-linux-gnu; \\
    elif [ "${TARGETPLATFORM}" = "linux/amd64" ] && [ "${BUILDPLATFORM}" != "linux/amd64" ] ; then \\
        apt-get install --no-install-recommends -y g++-x86-64-linux-gnu libc6-dev-amd64-cross libprotobuf-dev protobuf-compiler ca-certificates && \\
        rustup target add x86_64-unknown-linux-gnu; \\
    else \\
        apt-get install --no-install-recommends -y g++ libc6-dev libprotobuf-dev protobuf-compiler ca-certificates; \\
    fi

WORKDIR /app/

COPY /src/shipping/ /app/

RUN if [ "${TARGETPLATFORM}" = "linux/arm64" ] && [ "${BUILDPLATFORM}" != "linux/arm64" ] ; then \\
        env CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \\
            CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc \\
            CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-g++ \\
        cargo build -r --target aarch64-unknown-linux-gnu && \\
        cp /app/target/aarch64-unknown-linux-gnu/release/shipping /app/target/release/shipping && \\
        cp /app/target/aarch64-unknown-linux-gnu/release/healthcheck /app/target/release/healthcheck; \\
    elif [ "${TARGETPLATFORM}" = "linux/amd64" ] && [ "${BUILDPLATFORM}" != "linux/amd64" ] ; then \\
        env CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=x86_64-linux-gnu-gcc \\
            CC_x86_64_unknown_linux_gnu=x86_64-linux-gnu-gcc \\
            CXX_x86_64_unknown_linux_gnu=x86_64-linux-gnu-g++ \\
        cargo build -r --target x86_64-unknown-linux-gnu && \\
        mkdir -p /app/target/release && \\
        cp /app/target/x86_64-unknown-linux-gnu/release/shipping /app/target/release/shipping && \\
        cp /app/target/x86_64-unknown-linux-gnu/release/healthcheck /app/target/release/healthcheck; \\
    else \\
        cargo build -r; \\
    fi
'''
s2=re.sub(r'# Install dependencies.*?(?=\n\nFROM gcr\.io/distroless)', new.rstrip('\n'), s, count=1, flags=re.S)
assert s2!=s, "shipping Dockerfile block not replaced"
open(p,'w').write(s2)
PY

# --- guard: none of the old identifiers may survive in the built services -----------------------
OLD='oteldemo|Oteldemo|otelDemo|OpenTelemetry\.Demo|badhost|Invalid token|Otel Demo|OLJCESPC7Z|66VCHSJNUP|2ZYFJ3GM2N|Explorascope|Telescope'
for kv in $FLAGMAP; do OLD="$OLD|${kv%%=*}"; done
if grep -rInE --exclude-dir=node_modules --exclude-dir=.git "$OLD|[\"'\`]demo\.(payment|cart|product|user_context|ad|checkout|currency|shipping|quote|recommendation)" pb $SRC | grep -v "CHANGELOG\|README\|\.md:"; then
  echo "de-identify: old identifiers survived" >&2; exit 1
fi
[ "${BUILD:-1}" = 0 ] && { echo "de-identify: edits applied, BUILD=0 so not building"; git status --short | head -50; exit 0; }

ARGS="--build-arg OTEL_JAVA_AGENT_VERSION=$(grep ^OTEL_JAVA_AGENT_VERSION= .env | cut -d= -f2) --build-arg OPENTELEMETRY_CPP_VERSION=$(grep ^OPENTELEMETRY_CPP_VERSION= .env | cut -d= -f2)"
for svc in $SERVICES; do
  df=src/$svc/Dockerfile; [ $svc = cart ] && df=src/cart/src/Dockerfile
  echo "== $(date -u +%H:%M:%SZ) building $REGISTRY/$svc:$TAG ($PLATFORM)"
  docker buildx build --builder multi-platform --platform "$PLATFORM" $ARGS -f "$df" -t "$REGISTRY/$svc:$TAG" $PUSH . 2>&1 | grep -E "^#[0-9]+ (ERROR|CACHED)|error|ERROR|pushing|exporting|DONE [0-9]{2,}" | tail -15 || true
  docker buildx imagetools inspect "$REGISTRY/$svc:$TAG" >/dev/null 2>&1 && echo "== $(date -u +%H:%M:%SZ) pushed $svc" || { echo "== FAILED $svc" >&2; exit 1; }
done
echo "done: $SERVICES @ $REGISTRY:$TAG"
