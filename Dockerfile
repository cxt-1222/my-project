#官方ES基础镜像
FROM elasticsearch:8.17.0
#安装IK分词（版本严格和ES一致）
COPY --chown=1000:0 vendor/analysis-ik-8.17.0.zip /tmp/analysis-ik-8.17.0.zip
RUN echo "8426e752b16efacc13a7098ca84b08a61a163d1778570697636f45efeffe4c1a  /tmp/analysis-ik-8.17.0.zip" | sha256sum -c - \
    && elasticsearch-plugin install --batch file:///tmp/analysis-ik-8.17.0.zip \
    && rm /tmp/analysis-ik-8.17.0.zip
