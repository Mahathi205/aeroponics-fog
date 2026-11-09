FROM eclipse-temurin:21-jdk-jammy

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

# Compile the bundled iFogSim2 model while the image is being built.
RUN python3 -c "import ifogsim.runner as r; s=r.java_status(); assert s['available'], s['message']; print(r._compile(s['javac'], r._all_sources(), r._all_jars(), True))"

EXPOSE 10000
CMD ["sh", "-c", "python3 -m streamlit run dashboard.py --server.address=0.0.0.0 --server.port=${PORT:-10000} --server.headless=true --browser.gatherUsageStats=false"]
