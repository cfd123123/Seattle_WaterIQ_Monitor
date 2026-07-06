package com.example.waterbusiness.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TurbidityStateCheckResponse {

    private TurbidityStateSnapshotResponse snapshot;

    private boolean alertCreated;

    private String alertReason;
}
