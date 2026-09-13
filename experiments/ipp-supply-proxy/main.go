// SPDX-License-Identifier: MIT
// Optional experiment: correct one demonstrated IPP supply-color defect.
// No queue mutation, installer, frontend, scan/print job generation, or image logging.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/OpenPrinting/goipp"
)

const metadataLimit = 1024 * 1024
const requestMetadataLimit = 64 * 1024

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$`)
var hostnamePattern = regexp.MustCompile(`^[A-Za-z0-9.-]+\.local\.?$`)

type requestInfoKey struct{}
type requestInfo struct {
	operation uint16
	id        uint32
}
type replayBody struct {
	io.Reader
	io.Closer
}

type resolver struct {
	mu             sync.Mutex
	discover, uuid string
	target         *url.URL
	expires        time.Time
	client         *http.Client
}

// resolve serializes discovery and verifies the actual printer UUID/model before use.
// It never retries a submitted print operation following a transport failure.
func (r *resolver) resolve(ctx context.Context) (*url.URL, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.target != nil && time.Now().Before(r.expires) {
		return r.target, nil
	}
	discoveryContext, cancel := context.WithTimeout(ctx, 12*time.Second)
	defer cancel()
	output, err := exec.CommandContext(discoveryContext, r.discover, r.uuid).Output()
	if err != nil || len(output) > 8192 {
		return nil, errors.New("stable printer discovery failed")
	}
	var found struct {
		UUID     string `json:"uuid"`
		Hostname string `json:"hostname"`
		Port     int    `json:"ipp_port"`
	}
	if json.Unmarshal(output, &found) != nil || !strings.EqualFold(found.UUID, r.uuid) ||
		!hostnamePattern.MatchString(found.Hostname) || found.Port < 1 || found.Port > 65535 {
		return nil, errors.New("unexpected discovered printer identity")
	}
	target := &url.URL{Scheme: "http", Host: net.JoinHostPort(found.Hostname, strconv.Itoa(found.Port))}
	if err := verifyPrinter(ctx, r.client, target, r.uuid); err != nil {
		return nil, err
	}
	r.target, r.expires = target, time.Now().Add(60*time.Second)
	return target, nil
}

func singleString(attrs goipp.Attributes, name string) (string, bool) {
	var result string
	count := 0
	for _, attr := range attrs {
		if attr.Name != name {
			continue
		}
		count++
		if len(attr.Values) != 1 {
			return "", false
		}
		value, ok := attr.Values[0].V.(goipp.String)
		if !ok {
			return "", false
		}
		result = string(value)
	}
	return result, count == 1
}

func verifyPrinter(ctx context.Context, client *http.Client, target *url.URL, uuid string) error {
	query := goipp.NewRequest(goipp.DefaultVersion, goipp.OpGetPrinterAttributes, 1)
	query.Operation.Add(goipp.MakeAttr("attributes-charset", goipp.TagCharset, goipp.String("utf-8")))
	query.Operation.Add(goipp.MakeAttr("attributes-natural-language", goipp.TagLanguage, goipp.String("en")))
	uri := "ipp://" + target.Host + "/ipp/print"
	query.Operation.Add(goipp.MakeAttr("printer-uri", goipp.TagURI, goipp.String(uri)))
	query.Operation.Add(goipp.MakeAttr("requested-attributes", goipp.TagKeyword,
		goipp.String("printer-uuid"), goipp.String("printer-make-and-model")))
	body, err := query.EncodeBytes()
	if err != nil {
		return errors.New("identity request encoding failed")
	}
	request, err := http.NewRequestWithContext(ctx, "POST", target.String()+"/ipp/print", bytes.NewReader(body))
	if err != nil {
		return errors.New("identity request creation failed")
	}
	request.Header.Set("Content-Type", "application/ipp")
	response, err := client.Do(request)
	if err != nil {
		return errors.New("printer identity query failed")
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, metadataLimit+1))
	if err != nil || len(data) > metadataLimit || response.StatusCode != http.StatusOK {
		return errors.New("printer identity response invalid")
	}
	var message goipp.Message
	reader := bytes.NewReader(data)
	if message.Decode(reader) != nil || reader.Len() != 0 || message.Code >= 0x0100 || message.RequestID != 1 {
		return errors.New("printer identity response malformed")
	}
	actual, ok := singleString(message.Printer, "printer-uuid")
	model, modelOK := singleString(message.Printer, "printer-make-and-model")
	if !ok || !modelOK || !strings.EqualFold(strings.TrimPrefix(actual, "urn:uuid:"), uuid) || model != "Xerox WorkCentre 3025" {
		return errors.New("upstream is not the configured Xerox WorkCentre 3025")
	}
	return nil
}

// colorValueOffset walks the already decoded message's original wire records.
// In particular, do not re-encode this firmware's unsupported-value records:
// their nonzero text payload is accepted by Apple but normalized away by goipp.
// Only a top-level printer attribute can supply the returned offset; nested
// collections and binary values are skipped by their actual record lengths.
func colorValueOffset(data []byte, color string) (int, error) {
	offset, group, depth, found := 8, byte(0), 0, -1
	for offset < len(data) {
		tag := data[offset]
		offset++
		if tag <= 0x0f {
			if depth != 0 {
				return -1, errors.New("delimiter inside metadata collection")
			}
			if tag == byte(goipp.TagEnd) {
				if offset != len(data) || found < 0 {
					return -1, errors.New("missing or trailing color metadata")
				}
				return found, nil
			}
			group = tag
			continue
		}
		if offset+2 > len(data) {
			return -1, errors.New("truncated metadata name length")
		}
		nameLength := int(binary.BigEndian.Uint16(data[offset:]))
		offset += 2
		if nameLength > len(data)-offset {
			return -1, errors.New("truncated metadata name")
		}
		name := data[offset : offset+nameLength]
		offset += nameLength
		if offset+2 > len(data) {
			return -1, errors.New("truncated metadata value length")
		}
		valueLength := int(binary.BigEndian.Uint16(data[offset:]))
		offset += 2
		if valueLength > len(data)-offset {
			return -1, errors.New("truncated metadata value")
		}
		if group == byte(goipp.TagPrinterGroup) && depth == 0 && string(name) == "marker-colors" {
			if found >= 0 || tag != byte(goipp.TagName) || valueLength != 7 || string(data[offset:offset+valueLength]) != color {
				return -1, errors.New("ambiguous or unexpected wire color attribute")
			}
			found = offset
		}
		offset += valueLength
		if tag == byte(goipp.TagBeginCollection) {
			depth++
		}
		if tag == byte(goipp.TagEndCollection) {
			depth--
			if depth < 0 {
				return -1, errors.New("unexpected metadata collection end")
			}
		}
	}
	return -1, errors.New("unterminated metadata")
}

// sanitize edits only six ASCII color digits in a successful, complete GPA response.
// The upstream level is never computed, substituted, cached, or hardcoded.
func sanitize(data []byte, requestID uint32) ([]byte, bool, error) {
	var message goipp.Message
	reader := bytes.NewReader(data)
	if len(data) > metadataLimit || message.Decode(reader) != nil || reader.Len() != 0 || message.RequestID != requestID {
		return nil, false, errors.New("malformed or mismatched IPP metadata")
	}
	if message.Code >= 0x0100 {
		return data, false, nil
	}
	name, namesOK := singleString(message.Printer, "marker-names")
	typeName, typesOK := singleString(message.Printer, "marker-types")
	color, colorsOK := singleString(message.Printer, "marker-colors")
	if !namesOK || !typesOK || !colorsOK || !strings.HasPrefix(name, "Black Toner") ||
		(typeName != "toner" && typeName != "toner-cartridge") || !strings.EqualFold(color, "#FFFFFF") {
		return data, false, nil
	}
	position, err := colorValueOffset(data, color)
	if err != nil {
		return nil, false, err
	}
	modified := bytes.Clone(data)
	copy(modified[position+1:position+7], "000000")
	changes := 0
	for i := range data {
		if data[i] != modified[i] {
			if (data[i] != 'F' && data[i] != 'f') || modified[i] != '0' {
				return nil, false, errors.New("unexpected metadata change")
			}
			changes++
		}
	}
	if changes != 6 {
		return nil, false, errors.New("unexpected metadata change count")
	}
	return modified, true, nil
}

func modifyResponse(response *http.Response) error {
	info, ok := response.Request.Context().Value(requestInfoKey{}).(requestInfo)
	if !ok || info.operation != uint16(goipp.OpGetPrinterAttributes) || response.StatusCode != http.StatusOK {
		return nil
	}
	contentType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || contentType != "application/ipp" || response.Header.Get("Content-Encoding") != "" {
		return errors.New("unexpected IPP metadata content type or encoding")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, metadataLimit+1))
	response.Body.Close()
	if err != nil || len(data) > metadataLimit {
		return errors.New("IPP metadata exceeds bounded response size")
	}
	data, _, err = sanitize(data, info.id)
	if err != nil {
		return err
	}
	response.Body = io.NopCloser(bytes.NewReader(data))
	response.ContentLength = int64(len(data))
	response.Header.Set("Content-Length", strconv.Itoa(len(data)))
	response.TransferEncoding = nil
	response.Header.Del("Transfer-Encoding")
	// A body digest/validator for the original representation cannot validate changed bytes.
	response.Header.Del("ETag")
	response.Header.Del("Content-MD5")
	response.Header.Del("Digest")
	return nil
}

type resolveFunc func(context.Context) (*url.URL, error)

func handler(resolve resolveFunc, transport http.RoundTripper) http.Handler {
	proxy := &httputil.ReverseProxy{
		Transport:      transport,
		ModifyResponse: modifyResponse,
		FlushInterval:  -1,
		ErrorLog:       log.New(io.Discard, "", 0),
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			http.Error(w, "Printer communication failed; the request was not retried.", http.StatusBadGateway)
		},
		Rewrite: func(request *httputil.ProxyRequest) {
			target := request.In.Context().Value(upstreamKey{}).(*url.URL)
			request.SetURL(target)
			request.Out.Host = target.Host
			request.Out.Header.Del("Forwarded")
			request.Out.Header.Del("X-Forwarded-For")
			request.Out.Header.Del("X-Forwarded-Host")
			request.Out.Header.Del("X-Forwarded-Proto")
			request.Out.Header.Set("Accept-Encoding", "identity")
		},
	}
	return http.HandlerFunc(func(w http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Origin") != "" {
			http.Error(w, "Browser-origin requests are not accepted.", http.StatusForbidden)
			return
		}
		if request.Method == "GET" && request.URL.Path == "/healthz" {
			w.Header().Set("Content-Type", "text/plain")
			io.WriteString(w, "process running; printer availability is checked on each request\n")
			return
		}
		contentType, _, err := mime.ParseMediaType(request.Header.Get("Content-Type"))
		if request.Method != "POST" || request.URL.Path != "/ipp/print" || err != nil || contentType != "application/ipp" {
			http.Error(w, "Only IPP requests at /ipp/print are accepted.", http.StatusBadRequest)
			return
		}
		reader := bufio.NewReaderSize(request.Body, 4096)
		prefix, err := reader.Peek(8)
		if err != nil {
			http.Error(w, "Truncated IPP header.", http.StatusBadRequest)
			return
		}
		info := requestInfo{binary.BigEndian.Uint16(prefix[2:4]), binary.BigEndian.Uint32(prefix[4:8])}
		request.Body = replayBody{reader, request.Body}
		if info.operation == uint16(goipp.OpGetPrinterAttributes) {
			request.Body = http.MaxBytesReader(w, request.Body, requestMetadataLimit)
		}
		target, err := resolve(request.Context())
		if err != nil {
			// Resolver errors are our own fixed strings; never log request data or addresses.
			log.Print(err.Error())
			http.Error(w, "Configured printer is unavailable.", http.StatusServiceUnavailable)
			return
		}
		ctx := context.WithValue(request.Context(), requestInfoKey{}, info)
		ctx = context.WithValue(ctx, upstreamKey{}, target)
		proxy.ServeHTTP(w, request.WithContext(ctx))
	})
}

type upstreamKey struct{}

// Wait for shutdown to finish before returning to main. Serve returns as soon
// as listeners close, which happens before Shutdown has drained active requests.
func serveUntilStopped(ctx context.Context, server *http.Server, listener net.Listener, grace time.Duration) error {
	served := make(chan error, 1)
	go func() { served <- server.Serve(listener) }()
	select {
	case err := <-served:
		if err == http.ErrServerClosed {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), grace)
		defer cancel()
		if server.Shutdown(shutdown) != nil {
			server.Close()
		}
		err := <-served
		if err == http.ErrServerClosed {
			return nil
		}
		return err
	}
}

func main() {
	printerUUID := flag.String("uuid", "", "required stable physical printer UUID")
	discover := flag.String("discover", "", "required path to the existing native Bonjour discover executable")
	listen := flag.String("listen", "127.0.0.1:18326", "loopback address only")
	flag.Parse()
	if !uuidPattern.MatchString(*printerUUID) || *discover == "" {
		log.Fatal("A stable printer UUID and discover executable are required.")
	}
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		log.Fatal("The listener must be a numeric loopback address.")
	}
	transport := &http.Transport{
		Proxy:              nil,
		DialContext:        (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		DisableCompression: true,
		MaxIdleConns:       8, MaxIdleConnsPerHost: 4, IdleConnTimeout: 60 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second, ExpectContinueTimeout: time.Second,
	}
	lookup := &resolver{discover: *discover, uuid: strings.ToLower(*printerUUID),
		client: &http.Client{Transport: transport, Timeout: 15 * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}}
	server := &http.Server{Addr: *listen, Handler: handler(lookup.resolve, transport),
		ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 * 1024}
	listener, err := net.Listen("tcp", *listen)
	if err != nil {
		log.Fatal("Could not open loopback listener.")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	fmt.Fprintln(os.Stderr, "Optional Xerox supply proxy listening on loopback; no queue has been changed.")
	if err := serveUntilStopped(ctx, server, listener, 10*time.Second); err != nil {
		log.Fatal("Proxy server stopped unexpectedly.")
	}
}
