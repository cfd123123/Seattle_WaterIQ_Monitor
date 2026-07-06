package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "Single-site single-parameter (00060/63680) on-demand IV anomaly request")
public class SiteParamAnomalyIvRequest {

    @NotBlank
    @JsonProperty("site_no")
    @JsonAlias("siteNo")
    private String siteNo;

    @NotBlank
    @Pattern(regexp = "^(00060|63680)$", message = "仅支持 00060（流量）或 63680（浊度）")
    @JsonProperty("parameter_cd")
    @JsonAlias("parameterCd")
    private String parameterCd;

    @JsonProperty("iv_csv_path")
    @JsonAlias("ivCsvPath")
    private String ivCsvPath;
}
