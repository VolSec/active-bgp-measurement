FROM ubuntu:16.04
USER root

WORKDIR /client

# Copy everything to the container
# MUST have your certs in the certs/ folder already
COPY . .

# Build Dependencies

# Download and Install Bird 1.6.4
RUN wget ftp://bird.network.cz/pub/bird/bird-1.6.4.tar.gz
    && tar -xzvf bird-1.6.4.tar.gz

WORKDIR /client/bird-1.6.4
RUN ./configure \
    && make
    && make install
WORKDIR /client

# Prepare OpenVPN
RUN apt-get install openvpn
RUN mkdir /dev/net 
RUN mknod /dev/net/tun c 10 200 
RUN chmod 666 /dev/net/tun

ENTRYPOINT ["./peering"]
CMD ["openvpn status"]
