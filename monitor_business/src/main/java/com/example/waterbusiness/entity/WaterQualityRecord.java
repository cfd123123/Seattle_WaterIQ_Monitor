package com.example.waterbusiness.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "water_quality_record")
public class WaterQualityRecord {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "water_temperature_c")
    private Double waterTemperatureC;

    @Column(name = "ph")
    private Double pH;

    @Column(name = "dissolved_oxygen_mg_l")
    private Double dissolvedOxygenMgL;

    @Column(name = "conductivity_us_cm")
    private Double conductivityUSCm;

    @Column(name = "turbidity_ntu")
    private Double turbidityNTU;

    @Column(name = "nitrate_mg_l")
    private Double nitrateMgL;

    @Column(name = "ammonia_n_mg_l")
    private Double ammoniaNMgL;

    @Column(name = "total_phosphorus_mg_l")
    private Double totalPhosphorusMgL;

    @Column(name = "cod_mg_l")
    private Double codMgL;

    @Column(name = "bod_mg_l")
    private Double bodMgL;

    @Column(name = "heavy_metals_pb_ug_l")
    private Double heavyMetalsPbUgL;

    @Column(name = "pollution_level")
    private String pollutionLevel;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @Column(name = "sample_time")
    private LocalDateTime sampleTime;

    @Column(name = "station_id")
    private Long stationId;

    @Column(name = "trace_id", length = 64)
    private String traceId;

    @Enumerated(EnumType.STRING)
    @Column(name = "source", length = 32)
    private RecordSource source = RecordSource.API;
}
