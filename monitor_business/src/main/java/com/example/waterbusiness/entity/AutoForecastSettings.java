package com.example.waterbusiness.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Singleton row: enables scheduled auto-forecast for all registered USGS stations × flow/turbidity.
 */
@Data
@Entity
@Table(name = "auto_forecast_settings")
public class AutoForecastSettings {

    public static final long SINGLETON_ID = 1L;

    @Id
    @Column(nullable = false)
    private Long id = SINGLETON_ID;

    @Column(name = "enabled", nullable = false)
    private boolean enabled = false;

    @Column(name = "last_run_at")
    private LocalDateTime lastRunAt;

    @Column(name = "last_run_summary", length = 2000)
    private String lastRunSummary;
}
