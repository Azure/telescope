package main

// Tests cover duplicate source series, chunk preservation, and collision safety.

// Tests cover ordering, duplicate grouping, tombstones, rollback, and chunk fidelity.

import (
	"bytes"
	"encoding/binary"
	"hash/crc32"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/prometheus/prometheus/model/histogram"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/model/value"
	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
	"github.com/prometheus/prometheus/tsdb/chunks"
)

type sliceSeriesSource struct {
	records []seriesRecord
	index   int
}

func (s *sliceSeriesSource) Next() (seriesRecord, bool, error) {
	if s.index == len(s.records) {
		return seriesRecord{}, false, nil
	}
	record := s.records[s.index]
	s.index++
	return record, true, nil
}

func TestGroupedSeriesSourceMergesConsecutiveDuplicates(t *testing.T) {
	labelSetA := labels.FromStrings("__name__", "metric", "instance", "a")
	labelSetB := labels.FromStrings("__name__", "metric", "instance", "b")
	chunk10 := chunks.Meta{Ref: 10, MinTime: 0, MaxTime: 9}
	chunk20 := chunks.Meta{Ref: 20, MinTime: 10, MaxTime: 19}
	chunk30 := chunks.Meta{Ref: 30, MinTime: 20, MaxTime: 29}

	groups := groupedSeriesSource{source: &sliceSeriesSource{records: []seriesRecord{
		{ref: 1, labelSet: labelSetA, chunkMetas: []chunks.Meta{chunk10}},
		{ref: 2, labelSet: labelSetA, chunkMetas: []chunks.Meta{chunk10, chunk20}},
		{ref: 3, labelSet: labelSetB, chunkMetas: []chunks.Meta{chunk30}},
	}}}

	first, ok, err := groups.Next()
	if err != nil {
		t.Fatalf("first group: %v", err)
	}
	if !ok {
		t.Fatal("first group was missing")
	}
	if first.firstRef != storage.SeriesRef(1) || first.sourceSeries != 2 || first.duplicateChunks != 1 {
		t.Fatalf("unexpected first group metadata: %+v", first)
	}
	if !labels.Equal(first.labelSet, labelSetA) {
		t.Fatalf("unexpected first labelset: %s", first.labelSet)
	}
	assertChunkMetas(t, first.chunkMetas, []chunks.Meta{chunk10, chunk20})

	second, ok, err := groups.Next()
	if err != nil {
		t.Fatalf("second group: %v", err)
	}
	if !ok {
		t.Fatal("second group was missing")
	}
	if second.firstRef != storage.SeriesRef(3) || second.sourceSeries != 1 || second.duplicateChunks != 0 {
		t.Fatalf("unexpected second group metadata: %+v", second)
	}
	if !labels.Equal(second.labelSet, labelSetB) {
		t.Fatalf("unexpected second labelset: %s", second.labelSet)
	}
	assertChunkMetas(t, second.chunkMetas, []chunks.Meta{chunk30})

	if _, ok, err := groups.Next(); err != nil || ok {
		t.Fatalf("expected end of groups, got ok=%v err=%v", ok, err)
	}

	var stats rewriteStats
	stats.addGroup(first)
	stats.addGroup(second)
	expected := rewriteStats{
		SourceSeries:    3,
		WrittenGroups:   2,
		DuplicateSeries: 1,
		DuplicateChunks: 1,
	}
	if stats != expected {
		t.Fatalf("unexpected stats: got %+v, want %+v", stats, expected)
	}
}

func TestGroupedSeriesSourceCanonicalizesEquivalentLabelOrder(t *testing.T) {
	leftRaw := labelsInOrder("__name__", "metric", "instance", "a", "job", "api")
	rightRaw := labelsInOrder("job", "api", "__name__", "metric", "instance", "a")
	if labels.Equal(leftRaw, rightRaw) {
		t.Fatal("test labelsets unexpectedly have the same raw order")
	}

	chunk10 := chunks.Meta{Ref: 10, MinTime: 0, MaxTime: 9}
	groups := groupedSeriesSource{source: &sliceSeriesSource{records: []seriesRecord{
		newSeriesRecord(1, leftRaw, []chunks.Meta{chunk10}),
		newSeriesRecord(2, rightRaw, []chunks.Meta{chunk10}),
	}}}

	group, ok, err := groups.Next()
	if err != nil {
		t.Fatalf("group equivalent labelsets: %v", err)
	}
	if !ok {
		t.Fatal("equivalent labelsets were not grouped")
	}
	if group.sourceSeries != 2 || group.duplicateChunks != 1 {
		t.Fatalf("unexpected grouped metadata: %+v", group)
	}
	if !labels.Equal(group.labelSet, labels.FromStrings("__name__", "metric", "instance", "a", "job", "api")) {
		t.Fatalf("labelset was not canonicalized: %s", group.labelSet)
	}
	if _, ok, err := groups.Next(); err != nil || ok {
		t.Fatalf("expected one group, got ok=%v err=%v", ok, err)
	}
}

func TestSortedRunReordersByTargetLabelsAndStoresOnlyRefs(t *testing.T) {
	constants := []labels.Label{{Name: "tier", Value: "test"}}
	withoutSource, err := targetLabels(labels.FromStrings("__name__", "metric", "run", "r"), constants)
	if err != nil {
		t.Fatal(err)
	}
	withSource, err := targetLabels(labels.FromStrings("__name__", "metric", "run", "r", "source", "s"), constants)
	if err != nil {
		t.Fatal(err)
	}
	if labels.Compare(withSource, withoutSource) >= 0 {
		t.Fatalf("test target labels did not reorder: %s >= %s", withSource, withoutSource)
	}

	path, err := writeSortedRun(t.TempDir(), []sortRecord{
		{ref: 7, labelSet: withoutSource},
		{ref: 9, labelSet: withSource},
	})
	if err != nil {
		t.Fatalf("write sorted run: %v", err)
	}
	t.Cleanup(func() {
		_ = os.Remove(path)
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read sorted run: %v", err)
	}
	if len(data) != 16 {
		t.Fatalf("run size: got %d, want 16", len(data))
	}
	if first := binary.BigEndian.Uint64(data[:8]); first != 9 {
		t.Fatalf("first ref: got %d, want 9", first)
	}
	if second := binary.BigEndian.Uint64(data[8:]); second != 7 {
		t.Fatalf("second ref: got %d, want 7", second)
	}
}

func TestNormalizeChunkMetasSortsAndDeduplicates(t *testing.T) {
	chunk10 := chunks.Meta{Ref: 10, MinTime: 0, MaxTime: 9}
	chunk20 := chunks.Meta{Ref: 20, MinTime: 10, MaxTime: 19}

	got, duplicates, err := normalizeChunkMetas([]chunks.Meta{chunk20, chunk10, chunk10})
	if err != nil {
		t.Fatalf("normalize chunks: %v", err)
	}
	if duplicates != 1 {
		t.Fatalf("duplicate count: got %d, want 1", duplicates)
	}
	assertChunkMetas(t, got, []chunks.Meta{chunk10, chunk20})
}

func TestGroupedSeriesSourceRejectsNonConsecutiveDuplicate(t *testing.T) {
	labelSetA := labels.FromStrings("__name__", "metric", "instance", "a")
	labelSetB := labels.FromStrings("__name__", "metric", "instance", "b")
	groups := groupedSeriesSource{source: &sliceSeriesSource{records: []seriesRecord{
		{ref: 1, labelSet: labelSetA},
		{ref: 2, labelSet: labelSetB},
		{ref: 3, labelSet: labelSetA},
	}}}

	if _, ok, err := groups.Next(); err != nil || !ok {
		t.Fatalf("first group: ok=%v err=%v", ok, err)
	}
	if _, _, err := groups.Next(); err == nil || !strings.Contains(err.Error(), "out of order") {
		t.Fatalf("expected out-of-order error, got %v", err)
	}
}

func TestNormalizeChunkMetasRejectsOverlappingDistinctChunks(t *testing.T) {
	_, _, err := normalizeChunkMetas([]chunks.Meta{
		{Ref: 10, MinTime: 0, MaxTime: 10},
		{Ref: 20, MinTime: 10, MaxTime: 20},
	})
	if err == nil || !strings.Contains(err.Error(), "overlap") {
		t.Fatalf("expected overlap error, got %v", err)
	}
}

func TestNormalizeChunkMetasAllowsSourceRefsOutOfTimeOrder(t *testing.T) {
	early := chunks.Meta{Ref: 20, MinTime: 0, MaxTime: 9}
	late := chunks.Meta{Ref: 10, MinTime: 10, MaxTime: 19}

	got, duplicates, err := normalizeChunkMetas([]chunks.Meta{late, early})
	if err != nil {
		t.Fatalf("normalize chunks: %v", err)
	}
	if duplicates != 0 {
		t.Fatalf("duplicate count = %d, want 0", duplicates)
	}
	assertChunkMetas(t, got, []chunks.Meta{early, late})
}

func TestRawChunkCopyPreservesStaleAndHistogramBytes(t *testing.T) {
	workDir := filepath.Join(t.TempDir(), "raw-chunk-copy-test")
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		t.Fatal(err)
	}

	floatChunk := chunkenc.NewXORChunk()
	floatAppender, err := floatChunk.Appender()
	if err != nil {
		t.Fatal(err)
	}
	floatAppender.Append(0, 1, 1.5)
	floatAppender.Append(0, 2, math.Float64frombits(value.StaleNaN))

	xor2Chunk := chunkenc.NewXOR2Chunk()
	xor2Appender, err := xor2Chunk.Appender()
	if err != nil {
		t.Fatal(err)
	}
	xor2Appender.Append(0, 5, 2.5)

	histogramChunk := chunkenc.NewHistogramChunk()
	histogramAppender, err := histogramChunk.Appender()
	if err != nil {
		t.Fatal(err)
	}
	h := &histogram.Histogram{
		Count:         1,
		ZeroCount:     1,
		Sum:           3,
		ZeroThreshold: 1e-100,
		Schema:        1,
	}
	if newChunk, _, _, err := histogramAppender.AppendHistogram(nil, 0, 3, h, false); err != nil || newChunk != nil {
		t.Fatalf("append histogram: newChunk=%v err=%v", newChunk, err)
	}

	floatHistogramChunk := chunkenc.NewFloatHistogramChunk()
	floatHistogramAppender, err := floatHistogramChunk.Appender()
	if err != nil {
		t.Fatal(err)
	}
	fh := &histogram.FloatHistogram{
		Count:         1.5,
		ZeroCount:     1.5,
		Sum:           4,
		ZeroThreshold: 1e-100,
		Schema:        1,
	}
	if newChunk, _, _, err := floatHistogramAppender.AppendFloatHistogram(nil, 0, 4, fh, false); err != nil || newChunk != nil {
		t.Fatalf("append float histogram: newChunk=%v err=%v", newChunk, err)
	}

	sourceWriter, err := newRawChunkWriter(filepath.Join(workDir, "source"), chunks.DefaultChunkSegmentSize)
	if err != nil {
		t.Fatal(err)
	}
	sourceRecords := [][]byte{
		encodeChunkRecord(floatChunk),
		encodeChunkRecord(xor2Chunk),
		encodeChunkRecord(histogramChunk),
		encodeChunkRecord(floatHistogramChunk),
	}
	expectedSamples := []uint64{2, 1, 1, 1}
	expectedEncodings := []chunkenc.Encoding{
		chunkenc.EncXOR,
		chunkenc.EncXOR2,
		chunkenc.EncHistogram,
		chunkenc.EncFloatHistogram,
	}
	sourceRefs := make([]chunks.ChunkRef, 0, len(sourceRecords))
	for _, record := range sourceRecords {
		ref, err := sourceWriter.Write(record)
		if err != nil {
			t.Fatal(err)
		}
		sourceRefs = append(sourceRefs, ref)
	}
	if err := sourceWriter.Close(); err != nil {
		t.Fatal(err)
	}

	reader, err := newRawChunkReader(filepath.Join(workDir, "source"))
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	targetWriter, err := newRawChunkWriter(filepath.Join(workDir, "target"), chunks.DefaultChunkSegmentSize)
	if err != nil {
		t.Fatal(err)
	}
	for i, ref := range sourceRefs {
		raw, err := reader.Read(ref)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw.record, sourceRecords[i]) {
			t.Fatalf("source record %d changed while reading", i)
		}
		if raw.numSamples != expectedSamples[i] || raw.encoding != expectedEncodings[i] {
			t.Fatalf(
				"source record %d metadata = samples:%d encoding:%d, want samples:%d encoding:%d",
				i,
				raw.numSamples,
				raw.encoding,
				expectedSamples[i],
				expectedEncodings[i],
			)
		}
		if _, err := targetWriter.Write(raw.record); err != nil {
			t.Fatal(err)
		}
	}
	if err := targetWriter.Close(); err != nil {
		t.Fatal(err)
	}

	targetReader, err := newRawChunkReader(filepath.Join(workDir, "target"))
	if err != nil {
		t.Fatal(err)
	}
	defer targetReader.Close()
	for i, ref := range sourceRefs {
		raw, err := targetReader.Read(ref)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw.record, sourceRecords[i]) {
			t.Fatalf("target record %d changed", i)
		}
	}
}

func assertChunkMetas(t *testing.T, got, want []chunks.Meta) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("chunk count: got %d, want %d", len(got), len(want))
	}
	for i := range want {
		if !sameChunkMeta(got[i], want[i]) {
			t.Fatalf("chunk %d: got %+v, want %+v", i, got[i], want[i])
		}
	}
}

func encodeChunkRecord(chunk chunkenc.Chunk) []byte {
	data := chunk.Bytes()
	var prefix [binary.MaxVarintLen32]byte
	prefixSize := binary.PutUvarint(prefix[:], uint64(len(data)))
	record := make([]byte, 0, prefixSize+1+len(data)+crc32.Size)
	record = append(record, prefix[:prefixSize]...)
	record = append(record, byte(chunk.Encoding()))
	record = append(record, data...)
	checksum := crc32.Checksum(record[prefixSize:], castagnoliTable)
	var encodedChecksum [4]byte
	binary.BigEndian.PutUint32(encodedChecksum[:], checksum)
	return append(record, encodedChecksum[:]...)
}

func labelsInOrder(pairs ...string) labels.Labels {
	if len(pairs)%2 != 0 {
		panic("labelsInOrder requires name/value pairs")
	}
	builder := labels.NewScratchBuilder(len(pairs) / 2)
	for i := 0; i < len(pairs); i += 2 {
		builder.Add(pairs[i], pairs[i+1])
	}
	return builder.Labels()
}
