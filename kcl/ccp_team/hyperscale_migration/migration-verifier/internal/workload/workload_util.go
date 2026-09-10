package workload

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
)

// createPayload concatenates deterministic 32-byte SHA-256 digests, truncating the final digest to produce exactly size bytes.
func createPayload(seed, kind string, objectIndex, size int) []byte {
	if size <= 0 {
		return nil
	}

	payload := make([]byte, size)
	for blockIndex, offset := 0, 0; offset < size; blockIndex++ {
		// SHA-256 always produces a 32-byte digest.
		digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%s\x00%d\x00%d", seed, kind, objectIndex, blockIndex)))
		offset += copy(payload[offset:], digest[:])
	}
	return payload
}

func computeHash(payload []byte) string {
	digest := sha256.Sum256(payload)
	return hex.EncodeToString(digest[:])
}

func formatObjectName(kind string, objectIndex int) string {
	return fmt.Sprintf("migration-%s-%06d", strings.ToLower(kind), objectIndex)
}
