package main

// This tool rewrites a TSDB block while copying encoded chunk records byte-for-byte.
// It is intended for offline snapshot copies, never a live Prometheus data directory.

import (
	"bufio"
	"container/heap"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"hash"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/prometheus/common/model"
	"github.com/prometheus/prometheus/model/labels"
	"github.com/prometheus/prometheus/storage"
	"github.com/prometheus/prometheus/tsdb/chunkenc"
	"github.com/prometheus/prometheus/tsdb/chunks"
	"github.com/prometheus/prometheus/tsdb/index"
	"github.com/prometheus/prometheus/tsdb/tombstones"
	"golang.org/x/sys/unix"
)

type repeatedLabels []string

type rewriteStats struct {
	SourceSeries    int
	WrittenGroups   int
	DuplicateSeries int
	DuplicateChunks int
	SortRuns        int
	Digest          [sha256.Size]byte
	BlockStats      blockStats
}

type blockMeta struct {
	ULID       string          `json:"ulid"`
	MinTime    int64           `json:"minTime"`
	MaxTime    int64           `json:"maxTime"`
	Stats      blockStats      `json:"stats,omitempty"`
	Compaction json.RawMessage `json:"compaction"`
	Version    int             `json:"version"`
}

type blockStats struct {
	NumSamples          uint64 `json:"numSamples,omitempty"`
	NumFloatSamples     uint64 `json:"numFloatSamples,omitempty"`
	NumHistogramSamples uint64 `json:"numHistogramSamples,omitempty"`
	NumSeries           uint64 `json:"numSeries,omitempty"`
	NumChunks           uint64 `json:"numChunks,omitempty"`
	NumTombstones       uint64 `json:"numTombstones,omitempty"`
}

func (v *repeatedLabels) String() string {
	return strings.Join(*v, ",")
}

func (v *repeatedLabels) Set(value string) error {
	*v = append(*v, value)
	return nil
}

func main() {
	var (
		blockDir        string
		rawLabels       repeatedLabels
		sortChunkSeries int
	)

	flag.StringVar(&blockDir, "block-dir", "", "path to one Prometheus TSDB block directory")
	flag.Var(&rawLabels, "label", "constant label in name=value form; may be repeated")
	flag.IntVar(&sortChunkSeries, "sort-chunk-series", 100_000, "maximum series labelsets held in memory per sorted run")
	flag.Usage = func() {
		fmt.Fprintf(flag.CommandLine.Output(), "Usage: %s --block-dir DIR --label name=value [--label name=value ...]\n", os.Args[0])
		flag.PrintDefaults()
	}
	flag.Parse()

	if flag.NArg() != 0 {
		exitf("unexpected positional arguments: %s", strings.Join(flag.Args(), " "))
	}
	if blockDir == "" {
		exitf("--block-dir is required")
	}
	if sortChunkSeries <= 0 {
		exitf("--sort-chunk-series must be greater than zero")
	}

	constants, err := parseLabels(rawLabels)
	if err != nil {
		exitf("%v", err)
	}

	stats, err := rewriteBlock(context.Background(), blockDir, constants, sortChunkSeries)
	if err != nil {
		exitf("%v", err)
	}
	fmt.Printf(
		"source_series=%d written_groups=%d duplicate_count=%d duplicate_chunks=%d sort_runs=%d digest=%x block=%s\n",
		stats.SourceSeries,
		stats.WrittenGroups,
		stats.DuplicateSeries,
		stats.DuplicateChunks,
		stats.SortRuns,
		stats.Digest,
		blockDir,
	)
}

func exitf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", args...)
	os.Exit(1)
}

func parseLabels(raw []string) ([]labels.Label, error) {
	if len(raw) == 0 {
		return nil, errors.New("at least one --label is required")
	}

	result := make([]labels.Label, 0, len(raw))
	seen := make(map[string]struct{}, len(raw))
	for _, value := range raw {
		name, labelValue, ok := strings.Cut(value, "=")
		if !ok {
			return nil, fmt.Errorf("invalid --label %q: expected name=value", value)
		}
		if !model.UTF8Validation.IsValidLabelName(name) {
			return nil, fmt.Errorf("invalid label name %q", name)
		}
		if !model.LabelValue(labelValue).IsValid() {
			return nil, fmt.Errorf("label %q has a non-UTF-8 value", name)
		}
		if _, exists := seen[name]; exists {
			return nil, fmt.Errorf("constant label %q was specified more than once", name)
		}
		seen[name] = struct{}{}
		result = append(result, labels.Label{Name: name, Value: labelValue})
	}

	sort.Slice(result, func(i, j int) bool {
		return result[i].Name < result[j].Name
	})
	return result, nil
}

func rewriteBlock(ctx context.Context, blockDir string, constants []labels.Label, sortChunkSeries int) (rewriteStats, error) {
	blockDir, err := filepath.Abs(blockDir)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("resolve block directory: %w", err)
	}
	info, err := os.Lstat(blockDir)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("stat block directory: %w", err)
	}
	if !info.IsDir() {
		return rewriteStats{}, fmt.Errorf("block path %q is not a directory", blockDir)
	}
	sourceMeta, err := readBlockMeta(blockDir)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("read source meta: %w", err)
	}

	indexPath := filepath.Join(blockDir, "index")
	indexInfo, err := os.Stat(indexPath)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("stat source index: %w", err)
	}
	if !indexInfo.Mode().IsRegular() {
		return rewriteStats{}, fmt.Errorf("source index %q is not a regular file", indexPath)
	}

	source, err := index.NewFileReader(indexPath, index.DecodePostingsRaw)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("open source index: %w", err)
	}
	sourceChunks, err := newRawChunkReader(filepath.Join(blockDir, "chunks"))
	if err != nil {
		_ = source.Close()
		return rewriteStats{}, fmt.Errorf("open source chunks: %w", err)
	}
	var sourceTombstones *diskTombstoneReader
	sourceOpen := true
	defer func() {
		if sourceOpen {
			_ = source.Close()
			_ = sourceChunks.Close()
			if sourceTombstones != nil {
				_ = sourceTombstones.Close()
			}
		}
	}()

	stagingDir, err := createStagingBlockDir(blockDir, info.Mode().Perm())
	if err != nil {
		return rewriteStats{}, err
	}
	stagingPresent := true
	defer func() {
		if stagingPresent {
			_ = os.RemoveAll(stagingDir)
		}
	}()
	sourceTombstones, err = buildDiskTombstones(blockDir, stagingDir, sortChunkSeries)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("build source tombstone lookup: %w", err)
	}
	if err := validateTombstoneRefs(source, sourceTombstones); err != nil {
		return rewriteStats{}, fmt.Errorf("validate source tombstones: %w", err)
	}

	targetIndexPath := filepath.Join(stagingDir, "index")
	writer, err := index.NewWriter(ctx, targetIndexPath)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("create target index: %w", err)
	}
	targetChunks, err := newRawChunkWriter(filepath.Join(stagingDir, "chunks"), chunks.DefaultChunkSegmentSize)
	if err != nil {
		_ = writer.Close()
		return rewriteStats{}, fmt.Errorf("create target chunks: %w", err)
	}
	intervalWriter, err := newIntervalSidecarWriter(stagingDir)
	if err != nil {
		_ = writer.Close()
		_ = targetChunks.Close()
		return rewriteStats{}, fmt.Errorf("create tombstone sidecar: %w", err)
	}

	written, expectedDigest, writeErr := writeRelabeledIndex(
		ctx,
		source,
		sourceChunks,
		sourceTombstones,
		writer,
		targetChunks,
		intervalWriter,
		constants,
		stagingDir,
		sortChunkSeries,
	)
	closeErr := errors.Join(writer.Close(), targetChunks.Close(), intervalWriter.Close())
	if writeErr != nil || closeErr != nil {
		return rewriteStats{}, fmt.Errorf("write target block data: %w", errors.Join(writeErr, closeErr))
	}
	if err := sourceTombstones.Close(); err != nil {
		return rewriteStats{}, fmt.Errorf("close source tombstone lookup: %w", err)
	}
	if err := os.Remove(sourceTombstones.path); err != nil {
		return rewriteStats{}, fmt.Errorf("remove source tombstone lookup: %w", err)
	}
	sourceTombstones = nil
	if err := os.Chmod(targetIndexPath, indexInfo.Mode().Perm()); err != nil {
		return rewriteStats{}, fmt.Errorf("preserve index permissions: %w", err)
	}

	tombstoneCount, err := writeRemappedTombstones(
		ctx,
		stagingDir,
		targetIndexPath,
		intervalWriter.path,
		written.WrittenGroups,
	)
	if err != nil {
		return rewriteStats{}, fmt.Errorf("write target tombstones: %w", err)
	}
	if tombstoneCount != written.BlockStats.NumTombstones {
		return rewriteStats{}, fmt.Errorf(
			"wrote %d tombstones, expected %d",
			tombstoneCount,
			written.BlockStats.NumTombstones,
		)
	}
	if err := os.Remove(intervalWriter.path); err != nil {
		return rewriteStats{}, fmt.Errorf("remove tombstone sidecar: %w", err)
	}

	sourceMeta.Stats = written.BlockStats
	if err := writeBlockMeta(stagingDir, sourceMeta); err != nil {
		return rewriteStats{}, fmt.Errorf("write target meta: %w", err)
	}
	if err := validateReplacementBlock(
		ctx,
		stagingDir,
		constants,
		written.BlockStats,
		expectedDigest,
		sortChunkSeries,
	); err != nil {
		return rewriteStats{}, fmt.Errorf("validate target block: %w", err)
	}

	if err := errors.Join(source.Close(), sourceChunks.Close()); err != nil {
		return rewriteStats{}, fmt.Errorf("close source block: %w", err)
	}
	sourceOpen = false

	parentDir := filepath.Dir(blockDir)
	if err := errors.Join(syncDirectory(filepath.Join(stagingDir, "chunks")), syncDirectory(stagingDir), syncDirectory(parentDir)); err != nil {
		return rewriteStats{}, fmt.Errorf("sync target block: %w", err)
	}
	if err := atomicExchangeDirectories(stagingDir, blockDir); err != nil {
		return rewriteStats{}, fmt.Errorf("atomically exchange block directories: %w", err)
	}
	if err := syncDirectory(parentDir); err != nil {
		return written, fmt.Errorf("block was exchanged but syncing parent directory failed: %w", err)
	}
	if err := os.RemoveAll(stagingDir); err != nil {
		return written, fmt.Errorf("block was exchanged but removing old block failed: %w", err)
	}
	stagingPresent = false
	if err := syncDirectory(parentDir); err != nil {
		return written, fmt.Errorf("block was exchanged but syncing old-block removal failed: %w", err)
	}
	return written, nil
}

func createStagingBlockDir(blockDir string, mode os.FileMode) (string, error) {
	parent := filepath.Dir(blockDir)
	base := filepath.Base(blockDir)
	for attempt := 0; attempt < 100; attempt++ {
		path := filepath.Join(parent, fmt.Sprintf(".%s.relabel-%d-%d", base, os.Getpid(), attempt))
		err := os.Mkdir(path, mode)
		if err == nil {
			if err := os.Chmod(path, mode); err != nil {
				_ = os.Remove(path)
				return "", err
			}
			if err := syncDirectory(parent); err != nil {
				_ = os.Remove(path)
				return "", err
			}
			return path, nil
		}
		if !errors.Is(err, os.ErrExist) {
			return "", err
		}
	}
	return "", errors.New("could not reserve a staging block directory")
}

func readBlockMeta(dir string) (blockMeta, error) {
	data, err := os.ReadFile(filepath.Join(dir, "meta.json"))
	if err != nil {
		return blockMeta{}, err
	}
	var meta blockMeta
	if err := json.Unmarshal(data, &meta); err != nil {
		return blockMeta{}, err
	}
	return meta, nil
}

func writeBlockMeta(dir string, meta blockMeta) error {
	data, err := json.MarshalIndent(meta, "", "\t")
	if err != nil {
		return err
	}
	path := filepath.Join(dir, "meta.json")
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	if _, err := file.Write(data); err != nil {
		return errors.Join(err, file.Close())
	}
	return errors.Join(file.Sync(), file.Close())
}

func atomicExchangeDirectories(left, right string) error {
	return unix.Renameat2(unix.AT_FDCWD, left, unix.AT_FDCWD, right, unix.RENAME_EXCHANGE)
}

const chunkFormatV1 = byte(1)

var castagnoliTable = crc32.MakeTable(crc32.Castagnoli)

type rawChunk struct {
	record     []byte
	encoding   chunkenc.Encoding
	numSamples uint64
}

type rawChunkReader struct {
	files []*os.File
}

func newRawChunkReader(dir string) (*rawChunkReader, error) {
	entries, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return &rawChunkReader{}, nil
	}
	if err != nil {
		return nil, err
	}

	type segment struct {
		sequence int
		path     string
	}
	segments := make([]segment, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		sequence, err := strconv.Atoi(entry.Name())
		if err != nil {
			continue
		}
		segments = append(segments, segment{
			sequence: sequence,
			path:     filepath.Join(dir, entry.Name()),
		})
	}
	sort.Slice(segments, func(i, j int) bool {
		return segments[i].sequence < segments[j].sequence
	})

	reader := &rawChunkReader{}
	for i, segment := range segments {
		if segment.sequence != i+1 {
			_ = reader.Close()
			return nil, fmt.Errorf("chunk segments are not contiguous at %s", segment.path)
		}
		file, err := os.Open(segment.path)
		if err != nil {
			_ = reader.Close()
			return nil, err
		}
		reader.files = append(reader.files, file)

		var header [chunks.SegmentHeaderSize]byte
		if _, err := file.ReadAt(header[:], 0); err != nil {
			_ = reader.Close()
			return nil, fmt.Errorf("read chunk segment header %s: %w", segment.path, err)
		}
		if binary.BigEndian.Uint32(header[:chunks.MagicChunksSize]) != chunks.MagicChunks {
			_ = reader.Close()
			return nil, fmt.Errorf("invalid chunk magic in %s", segment.path)
		}
		if header[chunks.MagicChunksSize] != chunkFormatV1 {
			_ = reader.Close()
			return nil, fmt.Errorf("unsupported chunk format %d in %s", header[chunks.MagicChunksSize], segment.path)
		}
	}
	return reader, nil
}

func (r *rawChunkReader) Read(ref chunks.ChunkRef) (rawChunk, error) {
	segment, offset := chunks.BlockChunkRef(ref).Unpack()
	if segment < 0 || segment >= len(r.files) {
		return rawChunk{}, fmt.Errorf("chunk segment %d is out of range", segment)
	}

	var lengthPrefix [chunks.MaxChunkLengthFieldSize]byte
	if _, err := r.files[segment].ReadAt(lengthPrefix[:], int64(offset)); err != nil {
		return rawChunk{}, fmt.Errorf("read chunk length at ref %d: %w", ref, err)
	}
	dataLength, prefixSize := binary.Uvarint(lengthPrefix[:])
	if prefixSize <= 0 {
		return rawChunk{}, fmt.Errorf("invalid chunk length at ref %d", ref)
	}

	recordSize := prefixSize + chunks.ChunkEncodingSize + int(dataLength) + crc32.Size
	record := make([]byte, recordSize)
	if _, err := r.files[segment].ReadAt(record, int64(offset)); err != nil {
		return rawChunk{}, fmt.Errorf("read chunk record at ref %d: %w", ref, err)
	}
	dataStart := prefixSize + chunks.ChunkEncodingSize
	dataEnd := recordSize - crc32.Size
	if dataEnd-dataStart < 2 {
		return rawChunk{}, fmt.Errorf("chunk data at ref %d is too short", ref)
	}
	expectedCRC := binary.BigEndian.Uint32(record[dataEnd:])
	actualCRC := crc32.Checksum(record[prefixSize:dataEnd], castagnoliTable)
	if actualCRC != expectedCRC {
		return rawChunk{}, fmt.Errorf("chunk checksum mismatch at ref %d", ref)
	}

	encoding := chunkenc.Encoding(record[prefixSize])
	if !chunkenc.IsValidEncoding(encoding) {
		return rawChunk{}, fmt.Errorf("unsupported chunk encoding %d at ref %d", encoding, ref)
	}
	return rawChunk{
		record:     record,
		encoding:   encoding,
		numSamples: uint64(binary.BigEndian.Uint16(record[dataStart:dataEnd])),
	}, nil
}

func (r *rawChunkReader) Close() error {
	var result error
	for _, file := range r.files {
		result = errors.Join(result, file.Close())
	}
	r.files = nil
	return result
}

type rawChunkWriter struct {
	dir         string
	dirFile     *os.File
	file        *os.File
	writer      *bufio.Writer
	sequence    int
	offset      int64
	segmentSize int64
}

func newRawChunkWriter(dir string, segmentSize int64) (*rawChunkWriter, error) {
	if err := os.Mkdir(dir, 0o755); err != nil {
		return nil, err
	}
	dirFile, err := os.Open(dir)
	if err != nil {
		return nil, err
	}
	return &rawChunkWriter{
		dir:         dir,
		dirFile:     dirFile,
		sequence:    -1,
		segmentSize: segmentSize,
	}, nil
}

func (w *rawChunkWriter) Write(record []byte) (chunks.ChunkRef, error) {
	if w.file == nil || (w.offset > chunks.SegmentHeaderSize && w.offset+int64(len(record)) > w.segmentSize) {
		if err := w.cut(); err != nil {
			return 0, err
		}
	}
	if w.offset > int64(^uint32(0)) {
		return 0, fmt.Errorf("chunk segment offset %d exceeds block reference capacity", w.offset)
	}

	ref := chunks.ChunkRef(chunks.NewBlockChunkRef(uint64(w.sequence), uint64(w.offset)))
	if _, err := w.writer.Write(record); err != nil {
		return 0, err
	}
	w.offset += int64(len(record))
	return ref, nil
}

func (w *rawChunkWriter) cut() error {
	if err := w.closeTail(); err != nil {
		return err
	}
	w.sequence++
	path := filepath.Join(w.dir, fmt.Sprintf("%06d", w.sequence+1))
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}

	header := make([]byte, chunks.SegmentHeaderSize)
	binary.BigEndian.PutUint32(header[:chunks.MagicChunksSize], chunks.MagicChunks)
	header[chunks.MagicChunksSize] = chunkFormatV1
	if _, err := file.Write(header); err != nil {
		_ = file.Close()
		return err
	}
	w.file = file
	w.writer = bufio.NewWriterSize(file, 8<<20)
	w.offset = chunks.SegmentHeaderSize
	return w.dirFile.Sync()
}

func (w *rawChunkWriter) closeTail() error {
	if w.file == nil {
		return nil
	}
	result := errors.Join(w.writer.Flush(), w.file.Sync(), w.file.Close())
	w.file = nil
	w.writer = nil
	return result
}

func (w *rawChunkWriter) Close() error {
	return errors.Join(w.closeTail(), w.dirFile.Sync(), w.dirFile.Close())
}

type intervalSidecarWriter struct {
	path   string
	file   *os.File
	writer *bufio.Writer
}

func newIntervalSidecarWriter(dir string) (*intervalSidecarWriter, error) {
	path := filepath.Join(dir, ".tombstone-groups")
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, err
	}
	return &intervalSidecarWriter{
		path:   path,
		file:   file,
		writer: bufio.NewWriterSize(file, 64<<10),
	}, nil
}

func (w *intervalSidecarWriter) Write(intervals tombstones.Intervals) error {
	var encoded [8]byte
	binary.BigEndian.PutUint64(encoded[:], uint64(len(intervals)))
	if _, err := w.writer.Write(encoded[:]); err != nil {
		return err
	}
	for _, interval := range intervals {
		binary.BigEndian.PutUint64(encoded[:], uint64(interval.Mint))
		if _, err := w.writer.Write(encoded[:]); err != nil {
			return err
		}
		binary.BigEndian.PutUint64(encoded[:], uint64(interval.Maxt))
		if _, err := w.writer.Write(encoded[:]); err != nil {
			return err
		}
	}
	return nil
}

func (w *intervalSidecarWriter) Close() error {
	return errors.Join(w.writer.Flush(), w.file.Sync(), w.file.Close())
}

type intervalSidecarReader struct {
	file   *os.File
	reader *bufio.Reader
}

func newIntervalSidecarReader(path string) (*intervalSidecarReader, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	return &intervalSidecarReader{
		file:   file,
		reader: bufio.NewReaderSize(file, 64<<10),
	}, nil
}

func (r *intervalSidecarReader) Next() (tombstones.Intervals, error) {
	var encoded [8]byte
	if _, err := io.ReadFull(r.reader, encoded[:]); err != nil {
		return nil, err
	}
	count := binary.BigEndian.Uint64(encoded[:])
	intervals := make(tombstones.Intervals, 0, count)
	for range count {
		if _, err := io.ReadFull(r.reader, encoded[:]); err != nil {
			return nil, err
		}
		mint := int64(binary.BigEndian.Uint64(encoded[:]))
		if _, err := io.ReadFull(r.reader, encoded[:]); err != nil {
			return nil, err
		}
		maxt := int64(binary.BigEndian.Uint64(encoded[:]))
		intervals = append(intervals, tombstones.Interval{Mint: mint, Maxt: maxt})
	}
	return intervals, nil
}

func (r *intervalSidecarReader) EnsureEOF() error {
	_, err := r.reader.ReadByte()
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err == nil {
		return errors.New("tombstone sidecar contains extra records")
	}
	return err
}

func (r *intervalSidecarReader) Close() error {
	return r.file.Close()
}

type tombstoneRecord struct {
	ref        storage.SeriesRef
	mint, maxt int64
}

type diskTombstoneReader struct {
	path  string
	file  *os.File
	count int64
}

type tombstoneGetter interface {
	Get(storage.SeriesRef) (tombstones.Intervals, error)
}

func buildDiskTombstones(sourceDir, workDir string, chunkRecords int) (*diskTombstoneReader, error) {
	records := make([]tombstoneRecord, 0, chunkRecords)
	var runPaths []string
	cleanup := true
	defer func() {
		if cleanup {
			cleanupRunFiles(runPaths)
		}
	}()

	flush := func() error {
		if len(records) == 0 {
			return nil
		}
		path, err := writeTombstoneRun(workDir, records)
		if err != nil {
			return err
		}
		runPaths = append(runPaths, path)
		records = make([]tombstoneRecord, 0, chunkRecords)
		return nil
	}
	if err := scanSourceTombstones(sourceDir, func(record tombstoneRecord) error {
		records = append(records, record)
		if len(records) == chunkRecords {
			return flush()
		}
		return nil
	}); err != nil {
		return nil, err
	}
	if err := flush(); err != nil {
		return nil, err
	}

	path := filepath.Join(workDir, ".source-tombstones-sorted")
	count, err := mergeTombstoneRuns(runPaths, path)
	if err != nil {
		return nil, err
	}
	if err := removeRunFiles(runPaths); err != nil {
		return nil, err
	}
	runPaths = nil

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	cleanup = false
	return &diskTombstoneReader{path: path, file: file, count: count}, nil
}

func scanSourceTombstones(sourceDir string, consume func(tombstoneRecord) error) error {
	path := filepath.Join(sourceDir, tombstones.TombstonesFilename)
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return err
	}
	if info.Size() < 9 {
		return errors.New("source tombstone file is too short")
	}
	var header [5]byte
	if _, err := io.ReadFull(file, header[:]); err != nil {
		return err
	}
	if binary.BigEndian.Uint32(header[:4]) != tombstones.MagicTombstone || header[4] != 1 {
		return errors.New("unsupported source tombstone format")
	}

	entryBytes := info.Size() - 9
	checksum := crc32.New(castagnoliTable)
	reader := bufio.NewReaderSize(io.TeeReader(io.LimitReader(file, entryBytes), checksum), 64<<10)
	for {
		ref, err := binary.ReadUvarint(reader)
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return err
		}
		mint, err := binary.ReadVarint(reader)
		if err != nil {
			return err
		}
		maxt, err := binary.ReadVarint(reader)
		if err != nil {
			return err
		}
		if maxt < mint {
			return fmt.Errorf("source tombstone for ref %d has max time %d before min time %d", ref, maxt, mint)
		}
		if err := consume(tombstoneRecord{
			ref:  storage.SeriesRef(ref),
			mint: mint,
			maxt: maxt,
		}); err != nil {
			return err
		}
	}

	var expected [4]byte
	if _, err := file.ReadAt(expected[:], info.Size()-4); err != nil {
		return err
	}
	if checksum.Sum32() != binary.BigEndian.Uint32(expected[:]) {
		return errors.New("source tombstone checksum mismatch")
	}
	return nil
}

func writeTombstoneRun(dir string, records []tombstoneRecord) (path string, resultErr error) {
	sort.Slice(records, func(i, j int) bool {
		if records[i].ref != records[j].ref {
			return records[i].ref < records[j].ref
		}
		if records[i].mint != records[j].mint {
			return records[i].mint < records[j].mint
		}
		return records[i].maxt < records[j].maxt
	})
	file, err := os.CreateTemp(dir, ".tombstone-sort-run-*")
	if err != nil {
		return "", err
	}
	createdPath := file.Name()
	defer func() {
		if resultErr != nil {
			_ = file.Close()
			_ = os.Remove(createdPath)
		}
	}()

	writer := bufio.NewWriterSize(file, 64<<10)
	for _, record := range records {
		if err := writeFixedTombstone(writer, record); err != nil {
			return "", err
		}
	}
	if err := errors.Join(writer.Flush(), file.Sync(), file.Close()); err != nil {
		return "", err
	}
	return createdPath, nil
}

type tombstoneRunCursor struct {
	id     int
	file   *os.File
	reader *bufio.Reader
	head   tombstoneRecord
}

type tombstoneRunHeap []*tombstoneRunCursor

func (h tombstoneRunHeap) Len() int { return len(h) }
func (h tombstoneRunHeap) Less(i, j int) bool {
	if h[i].head.ref != h[j].head.ref {
		return h[i].head.ref < h[j].head.ref
	}
	if h[i].head.mint != h[j].head.mint {
		return h[i].head.mint < h[j].head.mint
	}
	if h[i].head.maxt != h[j].head.maxt {
		return h[i].head.maxt < h[j].head.maxt
	}
	return h[i].id < h[j].id
}
func (h tombstoneRunHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *tombstoneRunHeap) Push(value any) {
	*h = append(*h, value.(*tombstoneRunCursor))
}
func (h *tombstoneRunHeap) Pop() any {
	old := *h
	last := len(old) - 1
	value := old[last]
	old[last] = nil
	*h = old[:last]
	return value
}

func mergeTombstoneRuns(runPaths []string, targetPath string) (int64, error) {
	target, err := os.OpenFile(targetPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return 0, err
	}
	writer := bufio.NewWriterSize(target, 64<<10)
	var cursors []*tombstoneRunCursor
	var heads tombstoneRunHeap

	closeAll := func() error {
		var result error
		for _, cursor := range cursors {
			result = errors.Join(result, cursor.file.Close())
		}
		return result
	}
	for id, path := range runPaths {
		file, err := os.Open(path)
		if err != nil {
			return 0, errors.Join(err, closeAll(), target.Close())
		}
		cursor := &tombstoneRunCursor{id: id, file: file, reader: bufio.NewReaderSize(file, 64<<10)}
		cursors = append(cursors, cursor)
		record, ok, err := readFixedTombstone(cursor.reader)
		if err != nil {
			return 0, errors.Join(err, closeAll(), target.Close())
		}
		if ok {
			cursor.head = record
			heap.Push(&heads, cursor)
		}
	}

	var count int64
	for len(heads) > 0 {
		cursor := heap.Pop(&heads).(*tombstoneRunCursor)
		if err := writeFixedTombstone(writer, cursor.head); err != nil {
			return 0, errors.Join(err, closeAll(), target.Close())
		}
		count++
		record, ok, err := readFixedTombstone(cursor.reader)
		if err != nil {
			return 0, errors.Join(err, closeAll(), target.Close())
		}
		if ok {
			cursor.head = record
			heap.Push(&heads, cursor)
		}
	}
	if err := errors.Join(writer.Flush(), target.Sync(), target.Close(), closeAll()); err != nil {
		return 0, err
	}
	return count, nil
}

func writeFixedTombstone(writer io.Writer, record tombstoneRecord) error {
	var encoded [24]byte
	binary.BigEndian.PutUint64(encoded[0:8], uint64(record.ref))
	binary.BigEndian.PutUint64(encoded[8:16], uint64(record.mint))
	binary.BigEndian.PutUint64(encoded[16:24], uint64(record.maxt))
	_, err := writer.Write(encoded[:])
	return err
}

func readFixedTombstone(reader io.Reader) (tombstoneRecord, bool, error) {
	var encoded [24]byte
	_, err := io.ReadFull(reader, encoded[:])
	switch {
	case err == nil:
		return tombstoneRecord{
			ref:  storage.SeriesRef(binary.BigEndian.Uint64(encoded[0:8])),
			mint: int64(binary.BigEndian.Uint64(encoded[8:16])),
			maxt: int64(binary.BigEndian.Uint64(encoded[16:24])),
		}, true, nil
	case errors.Is(err, io.EOF):
		return tombstoneRecord{}, false, nil
	case errors.Is(err, io.ErrUnexpectedEOF):
		return tombstoneRecord{}, false, errors.New("partial fixed tombstone record")
	default:
		return tombstoneRecord{}, false, err
	}
}

func (r *diskTombstoneReader) readAt(position int64) (tombstoneRecord, error) {
	var encoded [24]byte
	if _, err := r.file.ReadAt(encoded[:], position*24); err != nil {
		return tombstoneRecord{}, err
	}
	return tombstoneRecord{
		ref:  storage.SeriesRef(binary.BigEndian.Uint64(encoded[0:8])),
		mint: int64(binary.BigEndian.Uint64(encoded[8:16])),
		maxt: int64(binary.BigEndian.Uint64(encoded[16:24])),
	}, nil
}

func (r *diskTombstoneReader) Get(ref storage.SeriesRef) (tombstones.Intervals, error) {
	low, high := int64(0), r.count
	for low < high {
		mid := low + (high-low)/2
		record, err := r.readAt(mid)
		if err != nil {
			return nil, err
		}
		if record.ref < ref {
			low = mid + 1
		} else {
			high = mid
		}
	}

	var intervals tombstones.Intervals
	for position := low; position < r.count; position++ {
		record, err := r.readAt(position)
		if err != nil {
			return nil, err
		}
		if record.ref != ref {
			break
		}
		intervals = intervals.Add(tombstones.Interval{Mint: record.mint, Maxt: record.maxt})
	}
	return intervals, nil
}

func (r *diskTombstoneReader) Iter(consume func(storage.SeriesRef, tombstones.Intervals) error) error {
	var (
		currentRef storage.SeriesRef
		intervals  tombstones.Intervals
		haveRef    bool
	)
	for position := int64(0); position < r.count; position++ {
		record, err := r.readAt(position)
		if err != nil {
			return err
		}
		if haveRef && record.ref != currentRef {
			if err := consume(currentRef, intervals); err != nil {
				return err
			}
			intervals = nil
		}
		currentRef = record.ref
		haveRef = true
		intervals = intervals.Add(tombstones.Interval{Mint: record.mint, Maxt: record.maxt})
	}
	if haveRef {
		return consume(currentRef, intervals)
	}
	return nil
}

func (r *diskTombstoneReader) Close() error {
	return r.file.Close()
}

func validateTombstoneRefs(source *index.Reader, sourceTombstones *diskTombstoneReader) error {
	builder := labels.NewScratchBuilder(0)
	return sourceTombstones.Iter(func(ref storage.SeriesRef, _ tombstones.Intervals) error {
		if err := source.Series(ref, &builder, nil); err != nil {
			return fmt.Errorf("tombstone references unknown source series %d: %w", ref, err)
		}
		return nil
	})
}

func writeRemappedTombstones(
	ctx context.Context,
	targetDir string,
	indexPath string,
	sidecarPath string,
	expectedSeries int,
) (uint64, error) {
	targetIndex, err := index.NewFileReader(indexPath, index.DecodePostingsRaw)
	if err != nil {
		return 0, err
	}
	sidecar, err := newIntervalSidecarReader(sidecarPath)
	if err != nil {
		_ = targetIndex.Close()
		return 0, err
	}

	path := filepath.Join(targetDir, tombstones.TombstonesFilename)
	stagingPath := path + ".staging"
	file, err := os.OpenFile(stagingPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		_ = targetIndex.Close()
		_ = sidecar.Close()
		return 0, err
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.Remove(stagingPath)
		}
	}()

	var header [5]byte
	binary.BigEndian.PutUint32(header[:4], tombstones.MagicTombstone)
	header[4] = 1
	if _, err := file.Write(header[:]); err != nil {
		return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
	}

	postings, err := allPostings(ctx, targetIndex)
	if err != nil {
		return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
	}
	checksum := crc32.New(castagnoliTable)
	var encoded [3 * binary.MaxVarintLen64]byte
	seriesCount := 0
	var total uint64
	for postings.Next() {
		intervals, err := sidecar.Next()
		if err != nil {
			return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
		}
		ref := postings.At()
		for _, interval := range intervals {
			size := binary.PutUvarint(encoded[:], uint64(ref))
			size += binary.PutVarint(encoded[size:], interval.Mint)
			size += binary.PutVarint(encoded[size:], interval.Maxt)
			if _, err := file.Write(encoded[:size]); err != nil {
				return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
			}
			_, _ = checksum.Write(encoded[:size])
			total++
		}
		seriesCount++
	}
	if err := postings.Err(); err != nil {
		return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
	}
	if seriesCount != expectedSeries {
		return 0, errors.Join(
			fmt.Errorf("target index has %d series, expected %d", seriesCount, expectedSeries),
			file.Close(),
			targetIndex.Close(),
			sidecar.Close(),
		)
	}
	if err := sidecar.EnsureEOF(); err != nil {
		return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
	}

	var encodedChecksum [4]byte
	binary.BigEndian.PutUint32(encodedChecksum[:], checksum.Sum32())
	if _, err := file.Write(encodedChecksum[:]); err != nil {
		return 0, errors.Join(err, file.Close(), targetIndex.Close(), sidecar.Close())
	}
	if err := errors.Join(file.Sync(), file.Close(), targetIndex.Close(), sidecar.Close()); err != nil {
		return 0, err
	}
	if err := os.Rename(stagingPath, path); err != nil {
		return 0, err
	}
	cleanup = false
	return total, syncDirectory(targetDir)
}

type seriesRecord struct {
	ref        storage.SeriesRef
	labelSet   labels.Labels
	chunkMetas []chunks.Meta
	deletions  tombstones.Intervals
}

type seriesSource interface {
	Next() (seriesRecord, bool, error)
}

type sortRecord struct {
	ref      storage.SeriesRef
	labelSet labels.Labels
}

type runCursor struct {
	id     int
	file   *os.File
	reader *bufio.Reader
}

func (c *runCursor) nextRef() (storage.SeriesRef, bool, error) {
	var encoded [8]byte
	_, err := io.ReadFull(c.reader, encoded[:])
	switch {
	case err == nil:
		return storage.SeriesRef(binary.BigEndian.Uint64(encoded[:])), true, nil
	case errors.Is(err, io.EOF):
		return 0, false, nil
	case errors.Is(err, io.ErrUnexpectedEOF):
		return 0, false, errors.New("sorted run has a partial series reference")
	default:
		return 0, false, err
	}
}

type runHead struct {
	cursor   *runCursor
	ref      storage.SeriesRef
	labelSet labels.Labels
}

type runHeadHeap []runHead

func (h runHeadHeap) Len() int {
	return len(h)
}

func (h runHeadHeap) Less(i, j int) bool {
	if comparison := labels.Compare(h[i].labelSet, h[j].labelSet); comparison != 0 {
		return comparison < 0
	}
	if h[i].ref != h[j].ref {
		return h[i].ref < h[j].ref
	}
	return h[i].cursor.id < h[j].cursor.id
}

func (h runHeadHeap) Swap(i, j int) {
	h[i], h[j] = h[j], h[i]
}

func (h *runHeadHeap) Push(value any) {
	*h = append(*h, value.(runHead))
}

func (h *runHeadHeap) Pop() any {
	old := *h
	last := len(old) - 1
	value := old[last]
	old[last] = runHead{}
	*h = old[:last]
	return value
}

type mergedRunSeriesSource struct {
	source           *index.Reader
	sourceTombstones tombstoneGetter
	constants        []labels.Label
	cursors          []*runCursor
	heads            runHeadHeap
	builder          labels.ScratchBuilder
	chunkMetas       []chunks.Meta
}

func newMergedRunSeriesSource(
	source *index.Reader,
	sourceTombstones tombstoneGetter,
	constants []labels.Label,
	runPaths []string,
) (*mergedRunSeriesSource, error) {
	merged := &mergedRunSeriesSource{
		source:           source,
		sourceTombstones: sourceTombstones,
		constants:        constants,
		builder:          labels.NewScratchBuilder(0),
	}
	for id, path := range runPaths {
		file, err := os.Open(path)
		if err != nil {
			_ = merged.Close()
			return nil, fmt.Errorf("open sorted run %q: %w", path, err)
		}
		cursor := &runCursor{
			id:     id,
			file:   file,
			reader: bufio.NewReaderSize(file, 64<<10),
		}
		merged.cursors = append(merged.cursors, cursor)

		ref, ok, err := cursor.nextRef()
		if err != nil {
			_ = merged.Close()
			return nil, fmt.Errorf("read first ref from sorted run %q: %w", path, err)
		}
		if !ok {
			continue
		}
		labelSet, err := merged.targetLabels(ref)
		if err != nil {
			_ = merged.Close()
			return nil, err
		}
		heap.Push(&merged.heads, runHead{cursor: cursor, ref: ref, labelSet: labelSet})
	}
	return merged, nil
}

func (s *mergedRunSeriesSource) Next() (seriesRecord, bool, error) {
	if len(s.heads) == 0 {
		return seriesRecord{}, false, nil
	}

	head := heap.Pop(&s.heads).(runHead)
	s.chunkMetas = s.chunkMetas[:0]
	if err := s.source.Series(head.ref, &s.builder, &s.chunkMetas); err != nil {
		return seriesRecord{}, false, fmt.Errorf("random-read source series %d: %w", head.ref, err)
	}
	labelSet, err := targetLabels(s.builder.Labels(), s.constants)
	if err != nil {
		return seriesRecord{}, false, fmt.Errorf("source series %d: %w", head.ref, err)
	}
	if !labels.Equal(labelSet, head.labelSet) {
		return seriesRecord{}, false, fmt.Errorf(
			"source series %d labels changed between sort and merge: %s != %s",
			head.ref,
			head.labelSet,
			labelSet,
		)
	}
	deletions, err := s.sourceTombstones.Get(head.ref)
	if err != nil {
		return seriesRecord{}, false, fmt.Errorf("read source tombstones %d: %w", head.ref, err)
	}

	nextRef, ok, err := head.cursor.nextRef()
	if err != nil {
		return seriesRecord{}, false, fmt.Errorf("advance sorted run %d: %w", head.cursor.id, err)
	}
	if ok {
		nextLabels, err := s.targetLabels(nextRef)
		if err != nil {
			return seriesRecord{}, false, err
		}
		heap.Push(&s.heads, runHead{
			cursor:   head.cursor,
			ref:      nextRef,
			labelSet: nextLabels,
		})
	}

	return seriesRecord{
		ref:        head.ref,
		labelSet:   labelSet,
		chunkMetas: append([]chunks.Meta(nil), s.chunkMetas...),
		deletions:  append(tombstones.Intervals(nil), deletions...),
	}, true, nil
}

func (s *mergedRunSeriesSource) targetLabels(ref storage.SeriesRef) (labels.Labels, error) {
	if err := s.source.Series(ref, &s.builder, nil); err != nil {
		return labels.EmptyLabels(), fmt.Errorf("random-read source labels %d: %w", ref, err)
	}
	labelSet, err := targetLabels(s.builder.Labels(), s.constants)
	if err != nil {
		return labels.EmptyLabels(), fmt.Errorf("source series %d: %w", ref, err)
	}
	return labelSet, nil
}

func (s *mergedRunSeriesSource) Close() error {
	var result error
	for _, cursor := range s.cursors {
		result = errors.Join(result, cursor.file.Close())
	}
	s.cursors = nil
	return result
}

func buildSortedRuns(
	ctx context.Context,
	source *index.Reader,
	constants []labels.Label,
	blockDir string,
	chunkSeries int,
) (runPaths []string, sourceSeries int, resultErr error) {
	defer func() {
		if resultErr != nil {
			cleanupRunFiles(runPaths)
		}
	}()

	postings, err := allPostings(ctx, source)
	if err != nil {
		return runPaths, 0, fmt.Errorf("get source series postings: %w", err)
	}
	builder := labels.NewScratchBuilder(0)
	records := make([]sortRecord, 0, chunkSeries)

	flush := func() error {
		if len(records) == 0 {
			return nil
		}
		path, err := writeSortedRun(blockDir, records)
		if err != nil {
			return err
		}
		runPaths = append(runPaths, path)
		records = make([]sortRecord, 0, chunkSeries)
		return nil
	}

	for postings.Next() {
		if sourceSeries%128 == 0 {
			if err := ctx.Err(); err != nil {
				return runPaths, sourceSeries, err
			}
		}

		ref := postings.At()
		if err := source.Series(ref, &builder, nil); err != nil {
			return runPaths, sourceSeries, fmt.Errorf("read source labels %d: %w", ref, err)
		}
		labelSet, err := targetLabels(builder.Labels(), constants)
		if err != nil {
			return runPaths, sourceSeries, fmt.Errorf("source series %d: %w", ref, err)
		}
		records = append(records, sortRecord{ref: ref, labelSet: labelSet})
		sourceSeries++
		if len(records) == chunkSeries {
			if err := flush(); err != nil {
				return runPaths, sourceSeries, err
			}
		}
	}
	if err := postings.Err(); err != nil {
		return runPaths, sourceSeries, fmt.Errorf("iterate source series: %w", err)
	}
	if err := flush(); err != nil {
		return runPaths, sourceSeries, err
	}
	return runPaths, sourceSeries, nil
}

func writeSortedRun(blockDir string, records []sortRecord) (path string, resultErr error) {
	sort.Slice(records, func(i, j int) bool {
		if comparison := labels.Compare(records[i].labelSet, records[j].labelSet); comparison != 0 {
			return comparison < 0
		}
		return records[i].ref < records[j].ref
	})

	file, err := os.CreateTemp(blockDir, ".index-relabel-run-*")
	if err != nil {
		return "", fmt.Errorf("create sorted run: %w", err)
	}
	createdPath := file.Name()
	path = createdPath
	defer func() {
		if resultErr != nil {
			_ = file.Close()
			_ = os.Remove(createdPath)
		}
	}()

	writer := bufio.NewWriterSize(file, 1<<20)
	var encoded [8]byte
	for _, record := range records {
		binary.BigEndian.PutUint64(encoded[:], uint64(record.ref))
		if _, err := writer.Write(encoded[:]); err != nil {
			return "", fmt.Errorf("write sorted run: %w", err)
		}
	}
	if err := writer.Flush(); err != nil {
		return "", fmt.Errorf("flush sorted run: %w", err)
	}
	if err := file.Sync(); err != nil {
		return "", fmt.Errorf("sync sorted run: %w", err)
	}
	if err := file.Close(); err != nil {
		return "", fmt.Errorf("close sorted run: %w", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		return "", fmt.Errorf("stat sorted run: %w", err)
	}
	expectedSize := int64(len(records) * 8)
	if info.Size() != expectedSize {
		return "", fmt.Errorf("sorted run size is %d bytes, expected %d", info.Size(), expectedSize)
	}
	return path, nil
}

func cleanupRunFiles(paths []string) {
	if err := removeRunFiles(paths); err != nil {
		fmt.Fprintf(os.Stderr, "warning: remove sorted runs: %v\n", err)
	}
}

func removeRunFiles(paths []string) error {
	var result error
	for _, path := range paths {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			result = errors.Join(result, fmt.Errorf("%s: %w", path, err))
		}
	}
	return result
}

type groupedSeries struct {
	firstRef        storage.SeriesRef
	labelSet        labels.Labels
	chunkMetas      []chunks.Meta
	deletions       tombstones.Intervals
	sourceSeries    int
	duplicateChunks int
}

type groupedSeriesSource struct {
	source  seriesSource
	pending *seriesRecord
	done    bool
}

func (s *groupedSeriesSource) Next() (groupedSeries, bool, error) {
	if s.done {
		return groupedSeries{}, false, nil
	}

	first, ok, err := s.nextRecord()
	if err != nil || !ok {
		s.done = !ok
		return groupedSeries{}, false, err
	}

	group := groupedSeries{
		firstRef:     first.ref,
		labelSet:     first.labelSet,
		chunkMetas:   append([]chunks.Meta(nil), first.chunkMetas...),
		deletions:    addIntervals(nil, first.deletions),
		sourceSeries: 1,
	}

readGroup:
	for {
		next, ok, err := s.source.Next()
		if err != nil {
			return groupedSeries{}, false, err
		}
		if !ok {
			s.done = true
			break
		}

		switch comparison := labels.Compare(next.labelSet, group.labelSet); {
		case comparison < 0:
			return groupedSeries{}, false, fmt.Errorf(
				"externally sorted target labelsets are out of order at ref %d: %s follows %s",
				next.ref,
				next.labelSet,
				group.labelSet,
			)
		case comparison > 0:
			s.pending = &next
			break readGroup
		default:
			group.sourceSeries++
			group.chunkMetas = append(group.chunkMetas, next.chunkMetas...)
			group.deletions = addIntervals(group.deletions, next.deletions)
		}
	}

	group.chunkMetas, group.duplicateChunks, err = normalizeChunkMetas(group.chunkMetas)
	if err != nil {
		return groupedSeries{}, false, fmt.Errorf("group %s: %w", group.labelSet, err)
	}
	return group, true, nil
}

func addIntervals(target tombstones.Intervals, additions tombstones.Intervals) tombstones.Intervals {
	for _, interval := range additions {
		target = target.Add(interval)
	}
	return target
}

func (s *groupedSeriesSource) nextRecord() (seriesRecord, bool, error) {
	if s.pending != nil {
		record := *s.pending
		s.pending = nil
		return record, true, nil
	}
	return s.source.Next()
}

func normalizeChunkMetas(input []chunks.Meta) ([]chunks.Meta, int, error) {
	normalized := append([]chunks.Meta(nil), input...)
	sort.Slice(normalized, func(i, j int) bool {
		switch {
		case normalized[i].MinTime != normalized[j].MinTime:
			return normalized[i].MinTime < normalized[j].MinTime
		case normalized[i].MaxTime != normalized[j].MaxTime:
			return normalized[i].MaxTime < normalized[j].MaxTime
		default:
			return normalized[i].Ref < normalized[j].Ref
		}
	})

	result := normalized[:0]
	byRef := make(map[chunks.ChunkRef]chunks.Meta, len(normalized))
	duplicateCount := 0
	for _, chunk := range normalized {
		if chunk.MaxTime < chunk.MinTime {
			return nil, duplicateCount, fmt.Errorf(
				"chunk ref %d has max time %d before min time %d",
				chunk.Ref,
				chunk.MaxTime,
				chunk.MinTime,
			)
		}
		if previous, exists := byRef[chunk.Ref]; exists {
			if sameChunkMeta(previous, chunk) {
				duplicateCount++
				continue
			}
			return nil, duplicateCount, fmt.Errorf(
				"chunk ref %d has conflicting metadata {%d,%d} and {%d,%d}",
				chunk.Ref,
				previous.MinTime,
				previous.MaxTime,
				chunk.MinTime,
				chunk.MaxTime,
			)
		}
		byRef[chunk.Ref] = chunk

		if len(result) > 0 {
			previous := result[len(result)-1]
			if chunk.MinTime <= previous.MaxTime {
				return nil, duplicateCount, fmt.Errorf(
					"distinct chunks overlap after grouping: ref %d {%d,%d} and ref %d {%d,%d}",
					previous.Ref,
					previous.MinTime,
					previous.MaxTime,
					chunk.Ref,
					chunk.MinTime,
					chunk.MaxTime,
				)
			}
		}
		result = append(result, chunk)
	}
	return result, duplicateCount, nil
}

func sameChunkMeta(left, right chunks.Meta) bool {
	return left.Ref == right.Ref && left.MinTime == right.MinTime && left.MaxTime == right.MaxTime
}

func (s *rewriteStats) addGroup(group groupedSeries) {
	s.SourceSeries += group.sourceSeries
	s.WrittenGroups++
	s.DuplicateSeries += group.sourceSeries - 1
	s.DuplicateChunks += group.duplicateChunks
}

func writeRelabeledIndex(
	ctx context.Context,
	source *index.Reader,
	sourceChunks *rawChunkReader,
	sourceTombstones tombstoneGetter,
	writer *index.Writer,
	targetChunks *rawChunkWriter,
	intervals *intervalSidecarWriter,
	constants []labels.Label,
	workDir string,
	sortChunkSeries int,
) (rewriteStats, [sha256.Size]byte, error) {
	var zeroDigest [sha256.Size]byte

	runPaths, sourceSeries, err := buildSortedRuns(ctx, source, constants, workDir, sortChunkSeries)
	if err != nil {
		return rewriteStats{}, zeroDigest, err
	}
	runsPresent := true
	defer func() {
		if runsPresent {
			cleanupRunFiles(runPaths)
		}
	}()

	if err := writeMergedSymbols(source.Symbols(), writer, constants); err != nil {
		return rewriteStats{}, zeroDigest, err
	}
	merged, err := newMergedRunSeriesSource(source, sourceTombstones, constants, runPaths)
	if err != nil {
		return rewriteStats{}, zeroDigest, err
	}
	groups := groupedSeriesSource{source: merged}

	stats := rewriteStats{SortRuns: len(runPaths)}
	digest := sha256.New()
	processErr := func() error {
		for {
			group, ok, err := groups.Next()
			if err != nil {
				return fmt.Errorf("merge sorted source series: %w", err)
			}
			if !ok {
				return nil
			}

			targetChunkMetas := make([]chunks.Meta, 0, len(group.chunkMetas))
			beginSeriesDigest(digest, group.labelSet, len(group.chunkMetas))
			for _, sourceMeta := range group.chunkMetas {
				raw, err := sourceChunks.Read(sourceMeta.Ref)
				if err != nil {
					return fmt.Errorf("read raw source chunk %d: %w", sourceMeta.Ref, err)
				}
				targetRef, err := targetChunks.Write(raw.record)
				if err != nil {
					return fmt.Errorf("write raw target chunk from ref %d: %w", sourceMeta.Ref, err)
				}
				targetMeta := chunks.Meta{
					Ref:     targetRef,
					MinTime: sourceMeta.MinTime,
					MaxTime: sourceMeta.MaxTime,
				}
				targetChunkMetas = append(targetChunkMetas, targetMeta)
				addChunkToDigest(digest, targetMeta, raw.record)
				addRawChunkStats(&stats.BlockStats, raw)
			}

			syntheticRef := storage.SeriesRef(stats.WrittenGroups + 1)
			if err := writer.AddSeries(syntheticRef, group.labelSet, targetChunkMetas...); err != nil {
				return fmt.Errorf("write target group from source ref %d: %w", group.firstRef, err)
			}
			if err := intervals.Write(group.deletions); err != nil {
				return fmt.Errorf("write target tombstone sidecar: %w", err)
			}
			addIntervalsToDigest(digest, group.deletions)
			stats.addGroup(group)
			stats.BlockStats.NumSeries++
			stats.BlockStats.NumTombstones += uint64(len(group.deletions))
		}
	}()
	closeErr := merged.Close()
	if processErr != nil || closeErr != nil {
		return stats, zeroDigest, errors.Join(processErr, closeErr)
	}
	if stats.SourceSeries != sourceSeries {
		return stats, zeroDigest, fmt.Errorf(
			"external merge read %d source series, initial scan found %d",
			stats.SourceSeries,
			sourceSeries,
		)
	}
	if err := removeRunFiles(runPaths); err != nil {
		return stats, zeroDigest, fmt.Errorf("remove sorted runs: %w", err)
	}
	runsPresent = false

	var resultDigest [sha256.Size]byte
	copy(resultDigest[:], digest.Sum(nil))
	stats.Digest = resultDigest
	return stats, resultDigest, nil
}

func beginSeriesDigest(digest hash.Hash, labelSet labels.Labels, chunkCount int) {
	writeDigestUvarint(digest, uint64(labelSet.Len()))
	labelSet.Range(func(label labels.Label) {
		writeDigestBytes(digest, []byte(label.Name))
		writeDigestBytes(digest, []byte(label.Value))
	})
	writeDigestUvarint(digest, uint64(chunkCount))
}

func addChunkToDigest(digest hash.Hash, chunk chunks.Meta, rawRecord []byte) {
	var encoded [8]byte
	binary.BigEndian.PutUint64(encoded[:], uint64(chunk.Ref))
	_, _ = digest.Write(encoded[:])
	binary.BigEndian.PutUint64(encoded[:], uint64(chunk.MinTime))
	_, _ = digest.Write(encoded[:])
	binary.BigEndian.PutUint64(encoded[:], uint64(chunk.MaxTime))
	_, _ = digest.Write(encoded[:])
	writeDigestBytes(digest, rawRecord)
}

func addIntervalsToDigest(digest hash.Hash, intervals tombstones.Intervals) {
	writeDigestUvarint(digest, uint64(len(intervals)))
	var encoded [8]byte
	for _, interval := range intervals {
		binary.BigEndian.PutUint64(encoded[:], uint64(interval.Mint))
		_, _ = digest.Write(encoded[:])
		binary.BigEndian.PutUint64(encoded[:], uint64(interval.Maxt))
		_, _ = digest.Write(encoded[:])
	}
}

func addRawChunkStats(stats *blockStats, raw rawChunk) {
	stats.NumChunks++
	stats.NumSamples += raw.numSamples
	switch raw.encoding {
	case chunkenc.EncHistogram, chunkenc.EncFloatHistogram:
		stats.NumHistogramSamples += raw.numSamples
	case chunkenc.EncXOR, chunkenc.EncXOR2:
		stats.NumFloatSamples += raw.numSamples
	}
}

func writeDigestBytes(digest hash.Hash, value []byte) {
	writeDigestUvarint(digest, uint64(len(value)))
	_, _ = digest.Write(value)
}

func writeDigestUvarint(digest hash.Hash, value uint64) {
	var encoded [binary.MaxVarintLen64]byte
	size := binary.PutUvarint(encoded[:], value)
	_, _ = digest.Write(encoded[:size])
}

func writeMergedSymbols(source index.StringIter, writer *index.Writer, constants []labels.Label) error {
	extraSet := make(map[string]struct{}, len(constants)*2)
	for _, constant := range constants {
		extraSet[constant.Name] = struct{}{}
		extraSet[constant.Value] = struct{}{}
	}
	extras := make([]string, 0, len(extraSet))
	for symbol := range extraSet {
		extras = append(extras, symbol)
	}
	sort.Strings(extras)

	extraIndex := 0
	hasSource := source.Next()
	for hasSource || extraIndex < len(extras) {
		switch {
		case !hasSource:
			if err := writer.AddSymbol(extras[extraIndex]); err != nil {
				return fmt.Errorf("add constant symbol %q: %w", extras[extraIndex], err)
			}
			extraIndex++
		case extraIndex == len(extras):
			symbol := source.At()
			if err := writer.AddSymbol(symbol); err != nil {
				return fmt.Errorf("copy source symbol %q: %w", symbol, err)
			}
			hasSource = source.Next()
		case source.At() < extras[extraIndex]:
			symbol := source.At()
			if err := writer.AddSymbol(symbol); err != nil {
				return fmt.Errorf("copy source symbol %q: %w", symbol, err)
			}
			hasSource = source.Next()
		case source.At() > extras[extraIndex]:
			if err := writer.AddSymbol(extras[extraIndex]); err != nil {
				return fmt.Errorf("add constant symbol %q: %w", extras[extraIndex], err)
			}
			extraIndex++
		default:
			symbol := source.At()
			if err := writer.AddSymbol(symbol); err != nil {
				return fmt.Errorf("copy shared symbol %q: %w", symbol, err)
			}
			hasSource = source.Next()
			extraIndex++
		}
	}
	if err := source.Err(); err != nil {
		return fmt.Errorf("iterate source symbols: %w", err)
	}
	return nil
}

func mergeLabels(source labels.Labels, constants []labels.Label) labels.Labels {
	merged := make([]labels.Label, 0, source.Len()+len(constants))
	source.Range(func(label labels.Label) {
		merged = append(merged, label)
	})
	merged = append(merged, constants...)
	return labels.New(merged...)
}

func targetLabels(source labels.Labels, constants []labels.Label) (labels.Labels, error) {
	canonical := canonicalizeLabels(source)
	for _, constant := range constants {
		if canonical.Has(constant.Name) {
			return labels.EmptyLabels(), fmt.Errorf("label %q already exists in %s", constant.Name, canonical)
		}
	}
	return mergeLabels(canonical, constants), nil
}

func newSeriesRecord(ref storage.SeriesRef, labelSet labels.Labels, chunkMetas []chunks.Meta) seriesRecord {
	return seriesRecord{
		ref:        ref,
		labelSet:   canonicalizeLabels(labelSet),
		chunkMetas: append([]chunks.Meta(nil), chunkMetas...),
	}
}

func canonicalizeLabels(source labels.Labels) labels.Labels {
	canonical := make([]labels.Label, 0, source.Len())
	source.Range(func(label labels.Label) {
		canonical = append(canonical, label)
	})
	return labels.New(canonical...)
}

func validateReplacementBlock(
	ctx context.Context,
	dir string,
	constants []labels.Label,
	expectedStats blockStats,
	expectedDigest [sha256.Size]byte,
	tombstoneChunkRecords int,
) error {
	meta, err := readBlockMeta(dir)
	if err != nil {
		return err
	}
	if meta.Stats != expectedStats {
		return fmt.Errorf("meta stats %+v do not match expected %+v", meta.Stats, expectedStats)
	}

	targetIndex, err := index.NewFileReader(filepath.Join(dir, "index"), index.DecodePostingsRaw)
	if err != nil {
		return err
	}
	targetChunks, err := newRawChunkReader(filepath.Join(dir, "chunks"))
	if err != nil {
		_ = targetIndex.Close()
		return err
	}
	targetTombstones, err := buildDiskTombstones(dir, dir, tombstoneChunkRecords)
	if err != nil {
		_ = targetIndex.Close()
		_ = targetChunks.Close()
		return err
	}

	validateErr := validateTargetData(
		ctx,
		targetIndex,
		targetChunks,
		targetTombstones,
		constants,
		expectedStats,
		expectedDigest,
	)
	closeErr := errors.Join(targetIndex.Close(), targetChunks.Close(), targetTombstones.Close())
	if validateErr != nil || closeErr != nil {
		return errors.Join(validateErr, closeErr)
	}
	if err := os.Remove(targetTombstones.path); err != nil {
		return fmt.Errorf("remove target tombstone validation lookup: %w", err)
	}

	return nil
}

func validateTargetData(
	ctx context.Context,
	targetIndex *index.Reader,
	targetChunks *rawChunkReader,
	targetTombstones tombstoneGetter,
	constants []labels.Label,
	expectedStats blockStats,
	expectedDigest [sha256.Size]byte,
) error {
	postings, err := allPostings(ctx, targetIndex)
	if err != nil {
		return err
	}

	builder := labels.NewScratchBuilder(0)
	var chunkMetas []chunks.Meta
	var previous labels.Labels
	var previousChunkRef chunks.ChunkRef
	haveChunkRef := false
	digest := sha256.New()
	var stats blockStats

	for postings.Next() {
		if stats.NumSeries%128 == 0 {
			if err := ctx.Err(); err != nil {
				return err
			}
		}
		ref := postings.At()
		chunkMetas = chunkMetas[:0]
		if err := targetIndex.Series(ref, &builder, &chunkMetas); err != nil {
			return fmt.Errorf("read target series %d: %w", ref, err)
		}

		labelSet := builder.Labels()
		if canonical := canonicalizeLabels(labelSet); !labels.Equal(labelSet, canonical) {
			return fmt.Errorf("target series %d labels are not canonical: %s", ref, labelSet)
		}
		if stats.NumSeries > 0 && labels.Compare(labelSet, previous) <= 0 {
			return fmt.Errorf("target series %d is not strictly ordered: %s follows %s", ref, labelSet, previous)
		}
		for _, constant := range constants {
			if !labelSet.Has(constant.Name) || labelSet.Get(constant.Name) != constant.Value {
				return fmt.Errorf("target series %d is missing constant %s=%q", ref, constant.Name, constant.Value)
			}
		}

		normalized, duplicateChunks, err := normalizeChunkMetas(chunkMetas)
		if err != nil {
			return fmt.Errorf("target series %d chunks: %w", ref, err)
		}
		if duplicateChunks != 0 {
			return fmt.Errorf("target series %d contains duplicate chunks", ref)
		}
		if err := compareChunkMetas(normalized, chunkMetas); err != nil {
			return fmt.Errorf("target series %d chunks are not normalized: %w", ref, err)
		}

		beginSeriesDigest(digest, labelSet, len(chunkMetas))
		for _, meta := range chunkMetas {
			if haveChunkRef && meta.Ref <= previousChunkRef {
				return fmt.Errorf(
					"target chunk ref %d is not greater than previous ref %d",
					meta.Ref,
					previousChunkRef,
				)
			}
			raw, err := targetChunks.Read(meta.Ref)
			if err != nil {
				return fmt.Errorf("read target chunk %d: %w", meta.Ref, err)
			}
			addChunkToDigest(digest, meta, raw.record)
			addRawChunkStats(&stats, raw)
			previousChunkRef = meta.Ref
			haveChunkRef = true
		}
		intervals, err := targetTombstones.Get(ref)
		if err != nil {
			return fmt.Errorf("read target tombstones %d: %w", ref, err)
		}
		addIntervalsToDigest(digest, intervals)
		stats.NumTombstones += uint64(len(intervals))
		stats.NumSeries++
		previous = labelSet.Copy()
	}
	if err := postings.Err(); err != nil {
		return err
	}
	if stats != expectedStats {
		return fmt.Errorf("validated stats %+v do not match expected %+v", stats, expectedStats)
	}

	var actualDigest [sha256.Size]byte
	copy(actualDigest[:], digest.Sum(nil))
	if actualDigest != expectedDigest {
		return fmt.Errorf("target digest %x does not match expected %x", actualDigest, expectedDigest)
	}
	return nil
}

func compareChunkMetas(source, target []chunks.Meta) error {
	if len(source) != len(target) {
		return fmt.Errorf("chunk count changed from %d to %d", len(source), len(target))
	}
	for i := range source {
		if source[i].Ref != target[i].Ref || source[i].MinTime != target[i].MinTime || source[i].MaxTime != target[i].MaxTime {
			return fmt.Errorf(
				"chunk %d changed from {ref:%d mint:%d maxt:%d} to {ref:%d mint:%d maxt:%d}",
				i,
				source[i].Ref,
				source[i].MinTime,
				source[i].MaxTime,
				target[i].Ref,
				target[i].MinTime,
				target[i].MaxTime,
			)
		}
	}
	return nil
}

func allPostings(ctx context.Context, reader *index.Reader) (index.Postings, error) {
	name, value := index.AllPostingsKey()
	return reader.Postings(ctx, name, value)
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	return errors.Join(directory.Sync(), directory.Close())
}
