package com.example.waterbusiness.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * One row per successful USGS single-parameter IV anomaly check (including available-but-not-anomaly runs), for 7-day trend detection counts;
 * decoupled from {@link AlertEvent}, which is only created when an IF anomaly is written.
 */
@Data
@Entity
@Table(name = "usgs_site_param_run")
public class UsgsSiteParamRun {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "station_id", nullable = false)
    private Long stationId;

    /** USGS parameter code: 00060 or 63680 */
    @Column(name = "parameter_cd", nullable = false, length = 16)
    private String parameterCd;

    @Column(name = "sample_timestamp", length = 64)
    private String sampleTimestamp;

    @Column(name = "is_anomaly")
    private Boolean isAnomaly;

    @Column(name = "alert_created")
    private Boolean alertCreated;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;
}
