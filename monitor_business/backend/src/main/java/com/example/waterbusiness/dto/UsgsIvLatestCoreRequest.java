package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Request body for Python {@code POST /usgs/iv/latest-core-params}. */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UsgsIvLatestCoreRequest {

    @JsonProperty("site_no")
    private String siteNo;

    @JsonProperty("iv_csv_path")
    private String ivCsvPath;
}
