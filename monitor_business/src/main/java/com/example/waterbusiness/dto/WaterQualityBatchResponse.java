package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Batch check result")
public class WaterQualityBatchResponse {

    @Schema(description = "Per-item outcomes")
    private List<WaterQualityBatchItemResult> results;
    @Schema(description = "Success count", example = "8")
    private int successCount;
    @Schema(description = "Failure count", example = "2")
    private int failCount;
}
