# Lightweight OCR Service Migration Summary

## Project Scope

This is a lightweight version of the INPI OCR service that uses the latest PaddleOCR version for text extraction without the resource-intensive PPStructure component.

## Key Changes from Original Service

### 1. OCR Engine
- **OLD**: PPStructureV3 with document structure analysis
- **NEW**: Latest PaddleOCR (3.2.0) with direct text extraction
- **Benefit**: Significantly reduced CPU/memory usage (~70% reduction)

### 2. Processing Approach
- **OLD**: Full document layout analysis with table detection
- **NEW**: Direct text extraction with line-by-line processing
- **Benefit**: Faster processing (sub-second per page)

### 3. Output Format
- **OLD**: Complex structured JSON with HTML tables and layout info
- **NEW**: Clean JSON with text content and bounding boxes
- **Benefit**: Simpler, more predictable output structure

### 4. Resource Requirements
- **OLD**: 2 CPU cores, 8GB RAM per worker
- **NEW**: 1 CPU core, 2GB RAM per worker
- **Benefit**: Can run 4x more workers with same resources

## Architecture Overview

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   PostgreSQL    │────▶│  OCR Worker  │────▶│     S3      │
│   Job Queue     │     │  PaddleOCR   │     │   Storage   │
└─────────────────┘     └──────────────┘     └─────────────┘
         │                      │                     │
         │                      ▼                     │
         │              ┌──────────────┐             │
         └─────────────▶│   Database   │◀────────────┘
                        │    Updates   │
                        └──────────────┘
```

## Technical Specifications

### Dependencies
- PaddleOCR 3.2.0 (latest stable)
- PaddlePaddle 3.1.0 (CPU optimized)
- PostgreSQL driver (psycopg2)
- AWS S3 SDK (boto3)
- Python 3.9+

### Processing Pipeline
1. **Document Retrieval**: Fetch PDF from S3
2. **PDF to Image**: Convert pages using pdf2image
3. **OCR Processing**: Extract text using PaddleOCR
4. **Data Formatting**: Structure as clean JSON
5. **Storage**: Upload results to S3
6. **Status Update**: Mark job complete in database

### Output Structure
```json
{
  "siren": "123456789",
  "pages": [
    {
      "page_number": 1,
      "text_blocks": [
        {
          "text": "Extracted text content",
          "confidence": 0.95,
          "bbox": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
        }
      ],
      "full_text": "Complete page text concatenated"
    }
  ],
  "metadata": {
    "ocr_version": "paddleocr-3.2.0",
    "processing_time_ms": 500,
    "total_pages": 1
  }
}
```

## Performance Targets
- **Processing Speed**: < 500ms per page
- **Memory Usage**: < 2GB per worker
- **CPU Usage**: < 100% per core
- **Accuracy**: > 95% for printed text
- **Concurrency**: 10+ workers per container

## Deployment Strategy

### Local Development
- Docker Compose with single worker
- Local PostgreSQL and MinIO (S3 alternative)

### Production (Azure)
- Azure Container Instances (ACI)
- Multiple regions for redundancy
- Auto-scaling based on queue size
- Shared PostgreSQL database
- AWS S3 for document storage

## Migration Path

1. **Phase 1**: Deploy lightweight service in parallel
2. **Phase 2**: Process new documents with both services
3. **Phase 3**: Compare outputs and validate accuracy
4. **Phase 4**: Gradually shift traffic to lightweight service
5. **Phase 5**: Decommission PPStructure service

## Benefits Summary

- **Cost Reduction**: ~75% lower compute costs
- **Speed Improvement**: 2-3x faster processing
- **Scalability**: 4x more parallel workers
- **Simplicity**: Cleaner codebase, easier maintenance
- **Reliability**: Fewer dependencies, less failure points

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Loss of table structure | Medium | Post-process text to detect tabular patterns |
| Reduced layout info | Low | Most use cases only need text |
| Different output format | Medium | Provide migration script for existing data |

## Timeline

- Week 1: Complete development and testing
- Week 2: Deploy to staging environment
- Week 3: Parallel processing and validation
- Week 4: Production deployment
- Week 5: Performance monitoring and optimization

## Success Metrics

- Processing time < 500ms per page (target: 300ms)
- Resource usage < 2GB RAM per worker
- OCR accuracy > 95%
- Zero data loss during migration
- 99.9% uptime SLA maintained

## Next Steps

1. Set up development environment
2. Implement core OCR worker with latest PaddleOCR
3. Create simplified data extractor
4. Update deployment scripts for lower resource requirements
5. Implement comprehensive testing suite
6. Document API changes for downstream consumers