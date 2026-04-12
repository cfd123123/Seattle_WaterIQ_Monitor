package com.example.waterbusiness.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TurbidityThresholdScanResult {

    private int stationsConsidered;

    private int alertsCreated;

    private int skippedNoData;

    private int skippedNoTrigger;

    private int skippedDuplicate;

    /**
     * Registered USGS station but IV has no parseable 63680 rows (excluded from turbidity threshold scan).
     */
    private int skippedRegisteredNo63680InIv;

    private String summary;
}
