package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotEmpty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Batch-read up to two recent 63680 points per site from IV")
public class TurbidityThresholdBatchRequest {

    @NotEmpty
    @JsonProperty("site_nos")
    @Schema(description = "List of USGS site numbers")
    private List<String> siteNos;

    @JsonProperty("iv_csv_path")
    @Schema(description = "Optional IV path; default AI data/usgs_puget_iv.csv")
    private String ivCsvPath;
}
