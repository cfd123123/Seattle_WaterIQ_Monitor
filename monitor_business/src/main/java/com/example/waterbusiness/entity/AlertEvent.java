package com.example.waterbusiness.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "alert_event")
public class AlertEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "water_quality_record_id")
    private Long waterQualityRecordId;

    @Column(name = "station_id")
    private Long stationId;

    @Column(name = "alert_type", length = 32)
    private String alertType;

    @Column(name = "severity", length = 16)
    private String severity;

    @Column(name = "status", length = 16)
    private String status;

    @Column(name = "pollution_level", length = 32)
    private String pollutionLevel;

    @Column(name = "title", length = 200)
    private String title;

    @Column(name = "detail", length = 1000)
    private String detail;

    @Column(name = "rule_code", length = 64)
    private String ruleCode;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @Column(name = "acknowledged_at")
    private LocalDateTime acknowledgedAt;

    @Column(name = "acknowledged_by", length = 64)
    private String acknowledgedBy;

    @Column(name = "closed_at")
    private LocalDateTime closedAt;

    @Column(name = "closed_by", length = 64)
    private String closedBy;

    @Column(name = "remark", length = 500)
    private String remark;
}
