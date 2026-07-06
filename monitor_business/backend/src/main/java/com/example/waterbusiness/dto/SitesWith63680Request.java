package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class SitesWith63680Request {

    @JsonProperty("iv_csv_path")
    private String ivCsvPath;
}
