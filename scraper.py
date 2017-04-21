import socket
import struct
from urllib.parse import urlparse, quote_from_bytes
from time import time
from os import urandom
import random
import string
import trackon
import requests
import bencode
import pprint


def scrape_submitted(t):
    pp = pprint.PrettyPrinter(width=999999, compact=True)
    parsed = urlparse(t)
    tnetloc = parsed.netloc
    try:
        failover_ip = socket.gethostbyname(parsed.hostname)
    except socket.error:
        failover_ip = ''
    # UDP scrape
    if parsed.port:  # If the tracker netloc has a port, try with udp
        udp_version = 'udp://' + tnetloc + '/announce'
        t1 = time()
        debug_udp = {'url': udp_version, 'time': int(t1)}
        try:
            parsed, raw, ip = announce_udp(udp_version)
            latency = int((time() - t1) * 1000)
            pretty_data = pp.pformat(parsed)
            debug_udp.update({'info': "Hex response: " + raw + '<br>' + "Parsed: " + pretty_data, 'status': 1, 'ip': ip})
            trackon.submitted_data.appendleft(debug_udp)
            return latency, parsed['interval'], udp_version
        except RuntimeError as e:
            debug_udp.update({'info': str(e), 'status': 0})
            if debug_udp['info'] != "Can't resolve IP":
                debug_udp['ip'] = failover_ip
            trackon.submitted_data.appendleft(debug_udp)
        print("UDP not working, trying HTTPS")

    # HTTPS scrape
    if not urlparse(t).port:
        https_version = 'https://' + tnetloc + ':443/announce'
    else:
        https_version = 'https://' + tnetloc + '/announce'
    t1 = time()
    debug_https = {'url': https_version, 'time': int(t1), 'ip': failover_ip}
    try:
        response = announce_http(https_version)
        latency = int((time() - t1) * 1000)
        pretty_data = pp.pformat(response)
        debug_https.update({'info': pretty_data, 'status': 1})
        trackon.submitted_data.appendleft(debug_https)
        return latency, response['interval'], https_version
    except RuntimeError as e:
        debug_https.update({'info': str(e), 'status': 0})
        "HTTPS not working, trying HTTP"
        trackon.submitted_data.appendleft(debug_https)

    # HTTP scrape
    if not urlparse(t).port:
        http_version = 'http://' + tnetloc + ':80/announce'
    else:
        http_version = 'http://' + tnetloc + '/announce'
    t1 = time()
    debug_http = {'url': http_version, 'time': int(t1), 'ip': failover_ip}
    try:
        response = announce_http(http_version)
        latency = int((time() - t1) * 1000)
        pretty_data = pp.pformat(response)
        debug_http.update({'info': pretty_data, 'status': 1})
        trackon.submitted_data.appendleft(debug_http)
        return latency, response['interval'], http_version
    except RuntimeError as e:
        debug_http.update({'info': str(e), 'status': 0})
        trackon.submitted_data.appendleft(debug_http)
    raise RuntimeError


def announce_http(tracker):
    print("Scraping HTTP: %s" % tracker)
    thash = trackerhash(type='http')
    pid = "-qB3360-" + ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(12)])
    request = "?info_hash=%s&peer_id=%s&port=6881&uploaded=0&downloaded=0&left=0&compact=1" % (thash, pid)
    url = tracker + request
    print(url)
    try:
        response = requests.get(url, timeout=10)
    except requests.Timeout:
        raise RuntimeError("HTTP timeout")
    except requests.HTTPError:
        raise RuntimeError("HTTP error")
    except requests.ConnectionError:
        raise RuntimeError("HTTP connection error")
    except requests.RequestException:
        raise RuntimeError("Ambiguous HTTP error")
    if response.status_code is not 200:
        raise RuntimeError("HTTP %s status code returned" % response.status_code)

    elif not response.content:
        raise RuntimeError("Got empty HTTP response")

    else:
        try:
            tracker_response = bencode.bdecode(response.text)
        except:
            raise RuntimeError("Can't bdecode the tracker response")

    if 'failure reason' in tracker_response:
        raise RuntimeError("Tracker error message: \"%s\"" % (tracker_response['failure reason']))
    elif 'peers' not in tracker_response:
        raise RuntimeError("Invalid response, 'peers' field is missing")
    pp = pprint.PrettyPrinter(width=999999, compact=True)
    pp.pprint(tracker_response)
    # if type(tracker_response['peers']) == str:
    # decode_binary_peers(tracker_response['peers']) TODO: decode binary peers response

    return tracker_response


def decode_binary_peers(peers):
    """ Return a list of IPs and ports, given a binary list of peers,
    from a tracker response. """
    peer_ips = list()
    presponse = [ord(i) for i in peers]
    while presponse:
        peer_ip = (('.'.join(str(x) for x in presponse[0:4]),
                    256 * presponse[4] + presponse[5]))
        peer_ips.append(peer_ip)
        presponse = presponse[6:]
    print(peer_ips)


def trackerhash(type):
    """Generate a random info_hash to be used with this tracker."""
    t_hash = urandom(20)
    if type == 'udp':
        return t_hash
    if type == 'http':
        return quote_from_bytes(t_hash)


def announce_udp(udp_version):
    thash = trackerhash(type='udp')
    parsed_tracker = urlparse(udp_version)
    print("Scraping UDP: %s " % udp_version)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(10)
    try:
        ip = socket.gethostbyname(parsed_tracker.hostname)
        conn = (ip, parsed_tracker.port)
    except socket.error:
        raise RuntimeError("Can't resolve IP")

    # Get connection ID
    req, transaction_id = udp_create_connection_request()
    sock.sendto(req, conn)
    try:
        buf = sock.recvfrom(2048)[0]
    except socket.timeout:
        raise RuntimeError("UDP timeout")
    connection_id = udp_parse_connection_response(buf, transaction_id)

    # Scrape away
    req, transaction_id = udp_create_announce_request(connection_id, thash)
    sock.sendto(req, conn)
    try:
        buf = sock.recvfrom(2048)[0]
    except socket.timeout:
        raise RuntimeError("UDP timeout")
    return udp_parse_announce_response(buf, transaction_id) + (ip,)


def udp_create_connection_request():
    connection_id = 0x41727101980  # default connection id
    action = 0x0  # action (0 = give me a new connection id)
    transaction_id = udp_get_transaction_id()
    buf = struct.pack("!q", connection_id)  # first 8 bytes is connection id
    buf += struct.pack("!i", action)  # next 4 bytes is action
    buf += struct.pack("!i", transaction_id)  # next 4 bytes is transaction id
    return buf, transaction_id


def udp_parse_connection_response(buf, sent_transaction_id):
    if len(buf) < 16:
        raise RuntimeError("Wrong response length getting connection id: %s" % len(buf))
    action = struct.unpack_from("!i", buf)[0]  # first 4 bytes is action

    res_transaction_id = struct.unpack_from("!i", buf, 4)[0]  # next 4 bytes is transaction id
    if res_transaction_id != sent_transaction_id:
        raise RuntimeError("Transaction ID doesnt match in connection response. Expected %s, got %s"
                           % (sent_transaction_id, res_transaction_id))

    if action == 0x0:
        connection_id = struct.unpack_from("!q", buf, 8)[0]  # unpack 8 bytes from byte 8, should be the connection_id
        return connection_id
    elif action == 0x3:
        error = struct.unpack_from("!s", buf, 8)
        raise RuntimeError("Error while trying to get a connection response: %s" % error)
    pass


def udp_create_announce_request(connection_id, thash):
    action = 0x1  # action (1 = announce)
    transaction_id = udp_get_transaction_id()
    buf = struct.pack("!q", connection_id)  # first 8 bytes is connection id
    buf += struct.pack("!i", action)  # next 4 bytes is action
    buf += struct.pack("!i", transaction_id)  # followed by 4 byte transaction id
    buf += struct.pack("!20s", thash)  # hash
    buf += struct.pack("!20s", thash)  # peer id, should be random
    buf += struct.pack("!q", 0x0)  # number of bytes downloaded
    buf += struct.pack("!q", 0x0)  # number of bytes left
    buf += struct.pack("!q", 0x0)  # number of bytes uploaded
    buf += struct.pack("!i", 0x2)  # event 0 denotes start of downloading
    buf += struct.pack("!i", 0x0)  # IP address set to 0. Response received to the sender of this packet
    key = udp_get_transaction_id()  # Unique key randomized by client
    buf += struct.pack("!i", key)
    buf += struct.pack("!i", -1)  # Number of peers required. Set to -1 for default
    buf += struct.pack("!i", 0x76FD)  # port on which response will be sent
    return buf, transaction_id


def udp_parse_announce_response(buf, sent_transaction_id):
    if len(buf) < 20:
        raise RuntimeError("Wrong response length while announcing: %s" % len(buf))
    action = struct.unpack_from("!i", buf)[0]  # first 4 bytes is action
    res_transaction_id = struct.unpack_from("!i", buf, 4)[0]  # next 4 bytes is transaction id
    if res_transaction_id != sent_transaction_id:
        raise RuntimeError("Transaction ID doesnt match in announce response! Expected %s, got %s"
                           % (sent_transaction_id, res_transaction_id))
    print("Raw response: " + buf.hex())
    if action == 0x1:
        ret = dict()
        offset = 8  # next 4 bytes after action is transaction_id, so data doesnt start till byte 8
        ret['interval'] = struct.unpack_from("!i", buf, offset)[0]
        offset += 4
        ret['leechers'] = struct.unpack_from("!i", buf, offset)[0]
        offset += 4
        ret['seeds'] = struct.unpack_from("!i", buf, offset)[0]
        offset += 4
        peers = list()
        x = 0
        while offset != len(buf):
            peers.append(dict())
            peers[x]['IP'] = struct.unpack_from("!i", buf, offset)[0]
            peers[x]['IP'] = socket.inet_ntoa(struct.pack("!i", peers[x]['IP']))
            offset += 4
            if offset >= len(buf):
                raise RuntimeError("Error while reading peer port")
            peers[x]['port'] = struct.unpack_from("!H", buf, offset)[0]
            offset += 2
            x += 1
        ret['peers'] = peers
        pp = pprint.PrettyPrinter(width=999999, compact=True)
        pp.pprint(ret)
        return ret, buf.hex()
    else:
        # an error occured, try and extract the error string
        error = struct.unpack_from("!s", buf, 8)
        raise RuntimeError("Error while annoucing: %s" % error)


def udp_get_transaction_id():
    return int(random.randrange(0, 255))
