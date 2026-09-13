// SPDX-License-Identifier: MIT
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
	"time"

	"github.com/OpenPrinting/goipp"
)

func fixture(t *testing.T, color, name string, level int) []byte {
	t.Helper()
	m := goipp.NewResponse(goipp.DefaultVersion, goipp.StatusOk, 101)
	m.Operation.Add(goipp.MakeAttr("attributes-charset", goipp.TagCharset, goipp.String("utf-8")))
	m.Printer.Add(goipp.MakeAttr("marker-colors", goipp.TagName, goipp.String(color)))
	m.Printer.Add(goipp.MakeAttr("marker-names", goipp.TagName, goipp.String(name)))
	m.Printer.Add(goipp.MakeAttr("marker-types", goipp.TagKeyword, goipp.String("toner")))
	m.Printer.Add(goipp.MakeAttr("marker-levels", goipp.TagInteger, goipp.Integer(level)))
	m.Printer.Add(goipp.MakeAttr("unrelated-vendor-data", goipp.TagString, goipp.Binary("#FFFFFF private untouched data")))
	data, err := m.EncodeBytes()
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestOnlyActualColorChangesAndLevelsSurvive(t *testing.T) {
	for _, level := range []int{-3, -2, -1, 0, 1, 39, 100} {
		data := fixture(t, "#FFFFFF", "Black Toner test", level)
		out, changed, err := sanitize(data, 101)
		if err != nil || !changed {
			t.Fatalf("level %d: changed=%v err=%v", level, changed, err)
		}
		want := bytes.Replace(data, []byte("#FFFFFF"), []byte("#000000"), 1)
		if !bytes.Equal(out, want) {
			t.Fatalf("level %d: non-color bytes changed", level)
		}
	}
}

func TestUnknownAndOtherSuppliesPassUnchanged(t *testing.T) {
	for _, item := range [][2]string{{"#000000", "Black Toner"}, {"#FFFFFF", "White Ink"}, {"none", "Black Toner"}} {
		data := fixture(t, item[0], item[1], 39)
		out, changed, err := sanitize(data, 101)
		if err != nil || changed || !bytes.Equal(data, out) {
			t.Fatalf("unexpected correction: %v", item)
		}
	}
}

func TestMalformedAndMismatchedMetadataRejected(t *testing.T) {
	data := fixture(t, "#FFFFFF", "Black Toner", 39)
	for _, bad := range [][]byte{nil, data[:7], data[:len(data)-1], append(append([]byte{}, data...), 'x')} {
		if _, _, err := sanitize(bad, 101); err == nil {
			t.Fatal("malformed input accepted")
		}
	}
	if _, _, err := sanitize(data, 999); err == nil {
		t.Fatal("mismatched request ID accepted")
	}
	if _, _, err := sanitize(make([]byte, metadataLimit+1), 101); err == nil {
		t.Fatal("oversized metadata accepted")
	}
}

func TestVendorUnsupportedValuePayloadIsPreserved(t *testing.T) {
	var message goipp.Message
	if err := message.Decode(bytes.NewReader(fixture(t, "#FFFFFF", "Black Toner fixture", 39))); err != nil {
		t.Fatal(err)
	}
	message.Code = goipp.Code(goipp.StatusOkIgnoredOrSubstituted)
	message.Groups = nil
	message.Unsupported.Add(goipp.MakeAttr("marker-change-time", goipp.TagUnsupportedValue, goipp.Void{}))
	message.Unsupported.Add(goipp.MakeAttr("marker-message", goipp.TagUnsupportedValue, goipp.Void{}))
	data, err := message.EncodeBytes()
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"marker-change-time", "marker-message"} {
		canonical := append([]byte{byte(goipp.TagUnsupportedValue), 0, byte(len(name))}, []byte(name)...)
		canonical = append(canonical, 0, 0)
		vendor := bytes.Clone(canonical)
		vendor[len(vendor)-1] = byte(len(name))
		vendor = append(vendor, []byte(name)...)
		if bytes.Count(data, canonical) != 1 {
			t.Fatal("bad unsupported-value fixture")
		}
		data = bytes.Replace(data, canonical, vendor, 1)
	}
	var decoded goipp.Message
	if err := decoded.Decode(bytes.NewReader(data)); err != nil {
		t.Fatal(err)
	}
	canonical, err := decoded.EncodeBytes()
	if err != nil || bytes.Equal(canonical, data) {
		t.Fatal("fixture did not reproduce vendor normalization gap")
	}
	out, changed, err := sanitize(data, 101)
	if err != nil || !changed || !bytes.Equal(out, bytes.Replace(data, []byte("#FFFFFF"), []byte("#000000"), 1)) {
		t.Fatalf("vendor records changed or color was not corrected: changed=%v error=%v", changed, err)
	}
}

func TestColorRecordInsideBinaryAndCollectionIsUntouched(t *testing.T) {
	m := goipp.NewResponse(goipp.DefaultVersion, goipp.StatusOk, 101)
	// An identical, complete wire attribute embedded inside a binary value must
	// never be mistaken for the actual top-level printer marker.
	record := append([]byte{byte(goipp.TagName), 0, 13}, []byte("marker-colors")...)
	record = append(record, 0, 7)
	record = append(record, []byte("#FFFFFF")...)
	m.Printer.Add(goipp.MakeAttr("vendor-binary", goipp.TagString, goipp.Binary(record)))
	collection := goipp.Collection{goipp.MakeAttr("marker-colors", goipp.TagName, goipp.String("#FFFFFF"))}
	m.Printer.Add(goipp.MakeAttr("vendor-collection", goipp.TagBeginCollection, collection))
	m.Printer.Add(goipp.MakeAttr("marker-colors", goipp.TagName, goipp.String("#FFFFFF")))
	m.Printer.Add(goipp.MakeAttr("marker-names", goipp.TagName, goipp.String("Black Toner fixture")))
	m.Printer.Add(goipp.MakeAttr("marker-types", goipp.TagKeyword, goipp.String("toner")))
	m.Printer.Add(goipp.MakeAttr("marker-levels", goipp.TagInteger, goipp.Integer(39)))
	data, err := m.EncodeBytes()
	if err != nil {
		t.Fatal(err)
	}
	out, changed, err := sanitize(data, 101)
	if err != nil || !changed {
		t.Fatalf("changed=%v error=%v", changed, err)
	}
	var result goipp.Message
	if err := result.Decode(bytes.NewReader(out)); err != nil {
		t.Fatal(err)
	}
	if !result.Printer[0].Equal(m.Printer[0]) || !result.Printer[1].Equal(m.Printer[1]) {
		t.Fatal("binary or nested collection was changed")
	}
	if color, ok := singleString(result.Printer, "marker-colors"); !ok || color != "#000000" {
		t.Fatal("actual printer color was not corrected")
	}
	if bytes.Count(out, []byte("#FFFFFF")) != 2 || bytes.Count(out, []byte("#000000")) != 1 {
		t.Fatal("unexpected color changes")
	}
}

func testProxy(t *testing.T, upstream http.Handler) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(upstream)
	t.Cleanup(server.Close)
	target, _ := url.Parse(server.URL)
	proxy := httptest.NewServer(handler(func(context.Context) (*url.URL, error) { return target, nil }, http.DefaultTransport))
	t.Cleanup(proxy.Close)
	return proxy
}

func header(operation uint16) []byte {
	b := []byte{2, 0, 0, 0, 0, 0, 0, 101}
	binary.BigEndian.PutUint16(b[2:4], operation)
	return b
}

func TestRealHTTPMetadataCorrection(t *testing.T) {
	data := fixture(t, "#FFFFFF", "Black Toner", 39)
	proxy := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.Copy(io.Discard, r.Body)
		w.Header().Set("Content-Type", "application/ipp")
		w.Write(data)
	}))
	response, err := http.Post(proxy.URL+"/ipp/print", "application/ipp", bytes.NewReader(header(uint16(goipp.OpGetPrinterAttributes))))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	result, _ := io.ReadAll(response.Body)
	if response.StatusCode != 200 || !bytes.Equal(result, bytes.Replace(data, []byte("#FFFFFF"), []byte("#000000"), 1)) {
		t.Fatalf("unexpected HTTP metadata response: %d", response.StatusCode)
	}
}

// The upstream must see initial bytes before the producer permits the rest.
// A proxy that reads an entire job before forwarding deadlocks this test.
func TestPrintBodiesStreamWithoutWholeJobBufferOrRetry(t *testing.T) {
	for _, chunked := range []bool{false, true} {
		t.Run(map[bool]string{false: "content-length", true: "chunked"}[chunked], func(t *testing.T) {
			prefixSeen := make(chan struct{})
			var calls atomic.Int32
			size := int64(16 * 1024 * 1024)
			synthetic := bytes.Repeat([]byte("streaming fixture; not printable image data\x00"), 1024)
			wantHash := sha256.New()
			wantHash.Write(header(uint16(goipp.OpPrintJob)))
			io.CopyN(wantHash, &repeatReader{data: synthetic}, size)
			proxy := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				first := make([]byte, 8)
				if _, err := io.ReadFull(r.Body, first); err != nil {
					t.Error(err)
					return
				}
				close(prefixSeen)
				hash := sha256.New()
				hash.Write(first)
				if _, err := io.Copy(hash, r.Body); err != nil {
					t.Error(err)
					return
				}
				if !bytes.Equal(hash.Sum(nil), wantHash.Sum(nil)) {
					t.Error("print bytes changed")
				}
				w.Header().Set("Content-Type", "application/ipp")
				w.Write(fixture(t, "#FFFFFF", "Black Toner", 39))
			}))
			reader, writer := io.Pipe()
			go func() {
				defer writer.Close()
				writer.Write(header(uint16(goipp.OpPrintJob)))
				select {
				case <-prefixSeen:
				case <-time.After(5 * time.Second):
					writer.CloseWithError(io.ErrNoProgress)
					return
				}
				io.CopyN(writer, &repeatReader{data: synthetic}, size)
			}()
			request, _ := http.NewRequest("POST", proxy.URL+"/ipp/print", reader)
			request.Header.Set("Content-Type", "application/ipp")
			if !chunked {
				request.ContentLength = size + 8
			}
			client := &http.Client{Timeout: 10 * time.Second}
			response, err := client.Do(request)
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			result, _ := io.ReadAll(response.Body)
			if calls.Load() != 1 || !bytes.Equal(result, fixture(t, "#FFFFFF", "Black Toner", 39)) {
				t.Fatal("non-GPA response changed or request duplicated")
			}
		})
	}
}

type repeatReader struct {
	data   []byte
	offset int
}

func (r *repeatReader) Read(p []byte) (int, error) {
	for i := range p {
		p[i] = r.data[r.offset%len(r.data)]
		r.offset++
	}
	return len(p), nil
}

func TestBrowserOriginCannotReachPrinter(t *testing.T) {
	var requests atomic.Int32
	proxy := testProxy(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests.Add(1) }))
	request, _ := http.NewRequest("POST", proxy.URL+"/ipp/print", bytes.NewReader(header(uint16(goipp.OpGetPrinterAttributes))))
	request.Header.Set("Content-Type", "application/ipp")
	request.Header.Set("Origin", "https://example.invalid")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 403 || requests.Load() != 0 {
		t.Fatal("browser-origin request reached printer")
	}
}

func TestShutdownDrainsInflightResponseBeforeReturning(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		io.WriteString(w, "complete response after shutdown began")
	})}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	served := make(chan error, 1)
	go func() { served <- serveUntilStopped(ctx, server, listener, 2*time.Second) }()
	response := make(chan string, 1)
	go func() {
		r, err := http.Get("http://" + listener.Addr().String())
		if err != nil {
			response <- err.Error()
			return
		}
		defer r.Body.Close()
		body, err := io.ReadAll(r.Body)
		if err != nil {
			response <- err.Error()
			return
		}
		response <- string(body)
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("request did not enter handler")
	}
	cancel()
	select {
	case <-served:
		close(release)
		t.Fatal("server returned before draining the in-flight request")
	case <-time.After(80 * time.Millisecond):
	}
	close(release)
	select {
	case err := <-served:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("shutdown did not finish")
	}
	select {
	case body := <-response:
		if body != "complete response after shutdown began" {
			t.Fatal(body)
		}
	case <-time.After(time.Second):
		t.Fatal("response did not finish")
	}
}

func TestShutdownBoundsStalledInflightRequest(t *testing.T) {
	entered, exited := make(chan struct{}), make(chan struct{})
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-r.Context().Done()
		close(exited)
	})}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	served := make(chan error, 1)
	go func() { served <- serveUntilStopped(ctx, server, listener, 80*time.Millisecond) }()
	client := make(chan error, 1)
	go func() {
		r, err := http.Get("http://" + listener.Addr().String())
		if r != nil {
			r.Body.Close()
		}
		client <- err
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("request did not enter handler")
	}
	start := time.Now()
	cancel()
	select {
	case err := <-served:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("stalled request blocked bounded shutdown")
	}
	if time.Since(start) < 70*time.Millisecond {
		t.Fatal("server skipped its drain grace period")
	}
	select {
	case <-exited:
	case <-time.After(time.Second):
		t.Fatal("stalled handler was not cancelled")
	}
	select {
	case err := <-client:
		if err == nil {
			t.Fatal("stalled response was incorrectly completed")
		}
	case <-time.After(time.Second):
		t.Fatal("client connection remained open")
	}
}
