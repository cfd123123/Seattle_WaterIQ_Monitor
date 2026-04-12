package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

@Data
@Schema(description = "Batch water quality check request")
public class WaterQualityBatchRequest {

    @NotEmpty(message = "至少一条")
    @Size(max = 100, message = "单次最多100条")
    @Valid
    @Schema(description = "Items (1–100)")
    private List<WaterQualityRequest> items;
}
