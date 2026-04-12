package com.example.waterbusiness.repository;

import com.example.waterbusiness.entity.WaterQualityRecord;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface WaterQualityRepository extends JpaRepository<WaterQualityRecord, Long> {

    WaterQualityRecord findTopByStationIdOrderBySampleTimeDescCreateTimeDesc(Long stationId);

    List<WaterQualityRecord> findByCreateTimeGreaterThanEqualAndCreateTimeLessThan(LocalDateTime from, LocalDateTime toExclusive);

    List<WaterQualityRecord> findByStationIdAndCreateTimeGreaterThanEqualAndCreateTimeLessThan(
            Long stationId,
            LocalDateTime from,
            LocalDateTime toExclusive
    );

    long countByCreateTimeGreaterThanEqualAndCreateTimeLessThan(LocalDateTime from, LocalDateTime toExclusive);

    @Query("select r.pollutionLevel, count(r) from WaterQualityRecord r group by r.pollutionLevel")
    List<Object[]> countByPollutionLevelAll();

    @Query("""
            select r.pollutionLevel, count(r)
            from WaterQualityRecord r
            where r.createTime >= :from and r.createTime < :toExclusive
            group by r.pollutionLevel
            """)
    List<Object[]> countByPollutionLevelBetween(
            @Param("from") LocalDateTime from,
            @Param("toExclusive") LocalDateTime toExclusive
    );
}
