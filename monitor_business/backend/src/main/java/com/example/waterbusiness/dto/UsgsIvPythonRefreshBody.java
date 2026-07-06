package com.example.waterbusiness.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Request body for Feign calls to Python {@code POST /refresh/usgs-iv}.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UsgsIvPythonRefreshBody {

    private int days;

    /** Merged with IV config sites, deduped, then fetch from NWIS (USGS ids from registered stations). */
    @JsonProperty("extra_site_nos")
    private List<String> extraSiteNos;
}
